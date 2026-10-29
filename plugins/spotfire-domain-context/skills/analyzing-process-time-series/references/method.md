# Method: how the engine works and why

Architecture of `tssme`, the reason behind each rule, and the defects that produced the
rules. Read this before you change a check or a threshold.

## Why there are four layers

An engine with two layers (a method and a domain) degrades in a predictable way. You
calibrate a band from the data in front of you and write it onto the class card, because the
card is where bands live. You add a check that encodes one industry's physics to the check
library, because that is where checks live. You put the asset id in the tag map template,
because that is what the columns look like. Each step is locally reasonable, and after enough
of them the "general" engine runs against one site only.

The separation is therefore structural:

| Layer | Holds | Rate of change |
|---|---|---|
| Engine | Method: prep, checks, statistics, reporting, the core schema | Rarely |
| Pack | Class knowledge: units, invariants, failure modes, confounders, domain vocabulary, domain checks | Slowly |
| Profile | Deployment facts: tag map, calibration overlay, data location | Constantly |
| Bundle | A named selection across the three below, plus a brief | Per release |

Two rules carry most of the weight.

**A calibration overlay may set only `normal`, `band_type`, `limits`, `source`,
`update_interval` and `required`.** It may not add a role, an invariant, a failure mode, a
confounder or a regime, and `apply_calibration` raises rather than merging. An overlay able to
redefine physics is a fork of the knowledge base: two assets would disagree about what the
equipment is. If an asset needs different physics, it is a different unit class.

**A pack may extend only `unit_class`, `persona` and `quantity`.** The other enums
(`severity`, `direction`, `band_type`, `onset`, `kind`, `control_role`, `invariant_kind`) are
properties the engine branches on. A pack adding `severity: catastrophic` would produce
findings the report cannot route and the caller cannot rank. `merged_schema` enforces this.

## Why the card is data and not prose

Writing a long document about pumps does not work as SME knowledge for three reasons:

1. Prose cannot be validated. Nothing can assert that every failure mode lists its
   confounders, or that every numeric bound carries a source.
2. Prose cannot be compiled. "Wax deposition raises measured drop while predicted drop stays
   flat" is executable only if the roles, directions and onset are structured fields.
3. Prose drifts from the data. A YAML band with a `source` field is reviewable like code.

The **structural** schema lives in the engine (`scripts/tssme/schema/core.yaml`) because the
shape of a card is a method concern. The **vocabulary** comes from whichever packs are
installed, merged by `packs.merged_schema()`. A card declaring `unit_class:
distillation_column` is valid exactly when some loaded pack claims that value. Process
engineers own the cards; the check library owns their interpretation.

## Pipeline order (`prep.build_context`)

1. `load_frame` (CSV) or `frame_from` (DataFrame) indexes by time. Unparseable timestamps
   become `NaT` and stay, so `dq_timestamp_regularity` can see them. Nothing is dropped
   silently.
2. `resolve` maps historian columns to canonical roles, for one asset if the frame holds
   several. It refuses to guess when a role matches multiple distinct columns, and it reports
   join duplicates (any column whose name differs only by a `(2)` counter suffix) rather than
   picking one quietly.
3. Numeric coercion, recording every value that failed to coerce. Text in a numeric column is
   usually a quality code, and turning it into a null hides a state the plant was reporting.
4. `_gate_invalid_rows` blanks rows where fewer than half the roles are populated. These are
   export or snapshot artifacts. Left in place, a single trailing blank row produced a
   CRITICAL violation of a card inequality that outranked everything real in the report.
5. `_compute_derived` evaluates the card's `derived` formulas. A formula that cannot be
   evaluated is recorded and skipped, never faked.
6. `_detect_rails` finds clamped extremes, here rather than in a check, so
   `dq_rail_saturation` and `phys_range` share one definition of what counts as a
   measurement.
7. `_segment_regimes` builds the regime label. Nothing compares a value to a threshold
   before this step.

## The two contracts

**Unit card schema** (`core.yaml`, extended by packs) binds SME knowledge to the check
library. Key fields:

- `roles`: canonical, plant-agnostic measurement names. Historian tag names never appear in a
  card; they live in the tag map.
- `band_type` on any `normal` band. `descriptive` means "what this asset does", so a wide
  miss means the card needs updating. `normative` means "what it should do", so a wide miss is
  the finding. Getting this backwards either buries a real problem or manufactures one.
- `requires_roles` on an invariant: a precondition the data must evidence. Without it an
  invariant that is only conditionally true fires a confident violation describing the
  missing precondition rather than the equipment. The gate lives in `checks/_gates.py` and is
  shared by every check that consumes invariants.
- `confounders` are benign explanations. `differentials` are competing faults. They are
  separate fields because they lead to different actions.

**Finding** (`findings.py`) is the uniform output of every check, with `kind` in `{defect,
candidate, verified, not_evaluated}`. `kind` is independent of severity and is what the report
routes on.

## Defect log

Each row was found by running the engine against real historian exports and reading the
output critically. Each has a regression test in `scripts/tests/test_tssme.py` that fails if
the defect returns.

| Defect | Symptom | Root cause | Fix |
|---|---|---|---|
| Drift check found nothing | `stat_regime_drift` returned zero findings on a visibly drifting series | Z-scored within regime, which subtracts each band's mean and absorbs the drift when band membership correlates with time | `_band_adjusted_trend`: band dummies plus time in one `lstsq` design matrix |
| False CRITICAL | A card inequality violated on exactly one sample | Trailing export snapshot row with all fields empty | `_gate_invalid_rows` blanks partial rows before any non-DQ check |
| False CRITICAL, again | Same violation after the gate was added | `NaN > NaN` is `False` in pandas, so evaluability read off the result was uniformly True | `_operand_mask` derives evaluability from the operands |
| Severity backwards | Band misses of 23 to 39 percent escalated to HIGH | A large excursion fraction is evidence the card is wrong, not the plant | Non-monotonic severity, plus `band_type` to exempt specification bands |
| Self-contradictory summary | "No consistent head degradation (+9.05%/yr across 11 bands)" | Agreement gate swallowed a large number and still claimed health | Split into healthy, inconsistent-across-bands and real-trend branches |
| One event, four findings | A step reported separately on four correlated tags | No clustering | Cluster detections by time, report once, name the corroborating roles |
| Changepoint detected nothing | After tightening the threshold to 2.0 sd, clean steps stopped firing | A balanced two-level step is capped at exactly 2.0 sd in globally z-scored units | Measure the shift against pooled within-segment sd |
| One event, three findings | A cluster split at 4 and 7 day gaps | CUSUM detection lag scales inversely with shift size, so tags trip days apart | Cluster window widened to 10 samples, with per-role detection times reported |
| Clamped samples double-reported | Twelve clipped temperature samples appeared as both a rail and a band excursion | Two checks, two definitions | Rails detected once in `prep`, excluded from band excursions |
| Wrong ZOH message | A role declared `kind: lab` reported as held constant while updating on 88 percent of samples | No branch for a mis-declared `kind` | Separate branch reporting a cadence or provenance contradiction |
| Card modelling error | One failure mode listed another failure mode as a confounder | Benign explanations conflated with competing faults | `differentials` added to the schema, with a validator hint when a failure mode id appears under `confounders` |
| Report reassured about unchecked things | "Not evaluated" and a downgraded candidate both filed under "Verified as healthy" | Report routed on severity | `Finding.kind`, and the report routes on it |
| Balance never tested | A mass balance written as `kind: balance` produced no output at all | No check consumed the `balance` kind | `rel_identity` evaluates `identity` and `balance` alike |
| Invariant vanished | An invariant naming a role absent from the export produced no output | The expression raised and the check skipped it silently | Missing operands, unparsed forms and too few samples are reported as `not_evaluated` |

The validator and the checks caught errors in the cards and in the engine itself. That works
only because the card is validated data and because "could not run" is a distinct outcome
from "passed".

## The regression baseline

There is no real reference dataset in this skill and there must not be one: a real export
carries one asset's operating envelope, and once it becomes the baseline, thresholds get
tuned until that asset looks right. The synthetic four-layer instance in `assets/examples/`
is the baseline instead; [example-walkthrough.md](example-walkthrough.md) tables each planted
fault against the check expected to catch it.

Findings about a particular asset belong in that asset's analysis output, not in the engine's
documentation.

## Known limitations

These are properties of the method, documented rather than tuned away.

- **Changepoint detection lags the event**, by tens of samples when the shift is comparable to
  the series' own spread. CUSUM is scaled globally on purpose (see the example walkthrough).
  Callers cluster nearby detections rather than matching timestamps.
- **A smooth swing can be reported as a step.** `stat_changepoint` segments on a shift in
  level and does not compare the jump against the local slope.
- **Signature matching is verbose by design.** Every candidate states its own weakness and is
  routed to its own section. Candidates are hypotheses to triage.
- **A confounder whose role never moves cannot be tested**, and "cannot be tested" is not
  "ruled out". Expect some confounders to be permanently unconfirmable at a given site.
- **Regime conditioning needs enough samples per band.** `regime_normalise` returns NaN for a
  band with fewer than five points rather than z-scoring from three.
- **The autocorrelation correction assumes AR(1).** For a residual with seasonal structure the
  correction is too small and the t-statistic is still optimistic. Newey-West would be the
  general estimator; it is not used because `se_inflation` is one number an engineer can
  check.
- **No multiplicity correction.** Effect-size gating is used instead of FDR control across the
  battery. This is a real gap.
- **Cross-unit analysis is out of scope.** A mass balance across several units, a leak
  calculation or a plant-wide reconciliation is a different structure from a unit card and is
  not attempted.
