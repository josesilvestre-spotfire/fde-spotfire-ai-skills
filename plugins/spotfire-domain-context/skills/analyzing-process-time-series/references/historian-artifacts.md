# Historian artifacts

A catalog of what process historians do to data on the way out, and what each one fakes when
you analyse the export as though it were a measurement record.

The working assumption in `tssme` is that **most apparent anomalies in historian data are
artifacts**. That is why `data_quality` runs before every other category and why a finding
built on a broken column is treated as worse than no finding: it spends an engineer's trip to
the field on an export bug.

Each entry gives what the artifact is, what it looks like in the data, **what it fakes**, and
which check catches it.

---

## 1. Compression (swinging door, deadband, exception reporting)

**What it is.** Historians do not store every sample. The archive keeps a point only when the
value departs from a linear interpolation of the stored points by more than a compression
deviation, and exception reporting drops it earlier still at the interface layer. The
retrieved series is a reconstruction.

**What it looks like.** Irregular native timestamps. Straight segments between stored points.
Variance lower than the instrument's real noise. Short excursions missing entirely.

**What it fakes.**
- *Reduced variance*, so every z-score and control limit computed from the export is too tight
  and the detector over-fires.
- *Damped correlations and distorted spectra*, so a correlation matrix or any oscillation
  diagnostic run on compressed data is not measuring the process. This is the specific result
  in Thornhill, Choudhury and Shah (2004).
- *A step that is actually a ramp*, when compression holds a slowly moving value and then
  records a catch-up point.

**Caught by.** Nothing directly, and that is a known gap. `dq_flatline` and
`dq_zero_order_hold` catch the extreme cases. The honest mitigation is to ask what the
compression deviation is set to for each tag before trusting any variance-based result.

## 2. Interpolation on retrieval

**What it is.** Asking a historian for evenly spaced samples makes it interpolate between
stored points. The grid is yours; the data underneath is not on it.

**What it looks like.** Perfectly regular timestamps, no gaps, and a suspiciously smooth
series.

**What it fakes.**
- *Confidence*. A regular cadence reads as a healthy dataset.
- *Inflated autocorrelation*, because interpolated points are deterministic functions of their
  neighbours. That shrinks `n_eff` and makes the autocorrelation correction over-conservative,
  which is the safe direction, but it also means the reported `lag1_autocorr` describes the
  retrieval method rather than the process.
- *Hidden gaps*. An outage becomes a straight line rather than a hole.

**Caught by.** `dq_timestamp_regularity` reports the cadence but cannot distinguish native
from interpolated. Ask for the raw archive when variance matters.

## 3. Aggregated export (hourly or daily averages)

**What it is.** The export is an average, minimum, maximum or time-weighted average over a
window, not a sample.

**What it looks like.** Round cadence, values that never hit the transmitter's real extremes.

**What it fakes.**
- *Absence of transients*. A five-minute pressure excursion vanishes into a daily mean.
- *A physically impossible operating point*. The average of two batches is a fluid that was
  never in the line. This one matters for NGL work: the daily-average composition of a
  fractionator that swung between two feeds is a composition that never existed, and every
  physical property derived from it is wrong.
- *Spurious smoothness*, which then reads as a healthy, well-controlled unit.

**Caught by.** Nothing automatic. It is a property of the export request, so it belongs in the
tag map's `source` field. Record the export cadence the data was pulled at, because a
daily export of a one-second tag is a different dataset from the tag.

## 4. Zero-order hold from merging cadences

**What it is.** A lab assay taken weekly, joined into a daily SCADA frame, is carried forward
between assays.

**What it looks like.** A role with very few distinct values and long flat runs.

**What it fakes.**
- *Independent evidence*. A signature that requires "specific gravity unchanged" is trivially
  satisfied by a value that physically cannot change in the export.
- *A step*, at each assay boundary, which `stat_changepoint` will happily detect and attribute
  to the process.
- *Stale confounder exclusion*. If the card says a viscosity change confounds a residual
  excursion, a held viscosity cannot exclude anything, and the analysis must say so rather
  than claim the confounder was ruled out.

**Caught by.** `dq_zero_order_hold`, which reports both directions: held far longer than the
declared cadence, and the inverse. In one real export the engine was built against, `specific_gravity` updates 8 times
in 350 samples against a declared 7 day cadence, with a longest hold of 70 days.

## 5. A lab role that is not a lab role

**What it is.** A tag declared as an assay that is actually a model output or a
temperature-corrected calculation.

**What it looks like.** A `lab` role that changes on nearly every sample.

**What it fakes.** *Independence.* The card treats lab staleness as a confounder that can be
excluded by a fresh assay. A modelled value is a function of the same sensors the analysis is
already using, so it cannot corroborate anything. In one real export the engine was built against, `viscosity` is
declared `lab` and changes on 308 of 350 samples; it is almost certainly ASTM D341 applied to
the temperature tag, which makes any "viscosity confirms the temperature story" reasoning
circular.

**Caught by.** `dq_zero_order_hold`, high-cadence branch.

## 6. Rail saturation and clamping

**What it is.** A value pinned at the transmitter's range end, at a configured clamp in the
DCS, or at a limit in a calculation.

**What it looks like.** Repeated exact minimum or exact maximum values in a signal that is
otherwise continuous, usually at a suspiciously round number.

**What it fakes.**
- *A band excursion with a process explanation*, when the reading is simply not a measurement.
- *A recalibrated band*. This is the compounding error: calibrate a `normal` band from the
  observed min and max and you have written the clamp into the card permanently. In one real
  export the engine was built against, `temperature` rails at exactly 20.0 and 110.0 F and `viscosity` at exactly
  1.51 and 5.83 cSt, 6 samples at each end.
- *Reduced apparent variance*, and a truncated distribution that breaks every normality
  assumption downstream.

**Caught by.** `_detect_rails` in `prep`, reported by `dq_rail_saturation`, and the pinned
samples are excluded from `phys_range` excursions so the same twelve samples are not reported
twice under two explanations. Bands must be calibrated from `unclamped_range`.

## 7. Frozen sensor

**What it is.** The transmitter stops updating but the tag keeps reporting its last value.

**What it looks like.** A long run of one identical value on a role that should move.

**What it fakes.** *Stability.* A frozen tag is the most reassuring thing in a dataset and the
most dangerous. It also drags any average toward the frozen value and suppresses the variance
used to normalise everything else.

**Caught by.** `dq_flatline`, gated against the role's declared update cadence so that a
genuinely steady value on a coarse transmitter is not reported as frozen.

## 8. Bad-quality codes and text in numeric columns

**What it is.** Historians report status as well as value: `Bad`, `Comm Fail`, `I/O Timeout`,
`Shutdown`, `Configure`, `Pt Created`, and numeric sentinels such as `-9999`, `0`, `32767`.

**What it looks like.** Text in a numeric column, or a value far outside the physical range.

**What it fakes.**
- *A catastrophic excursion*, when `-9999` is coerced to a number and read as a pressure.
- *Health*, when the same code is silently coerced to null and the row quietly disappears
  from the denominator.

**Caught by.** Numeric coercion in `prep` records every value that failed to coerce rather
than dropping it, because text in a numeric column is a state the plant was reporting. A
numeric sentinel inside the coercible range is caught only by the card's hard `limits`, which
is the main reason hard limits are `critical` and never suppressed.

## 9. Null rendered as zero

**What it is.** A missing value written as `0` somewhere in the export or reporting chain.

**What it looks like.** A plausible number.

**What it fakes.** Almost anything. Zero flow reads as a shutdown. Zero pressure violates a
hard limit. Zero in a denominator produces an infinite derived value. Worst case it is
physically plausible and silently biases every mean.

**Caught by.** Hard limits, and `dq_flatline` if there are enough of them in a row. A single
plausible zero is not caught, which is why the card's `limits` should exclude zero for any
quantity that cannot physically be zero while the unit is running.

## 10. Partial and snapshot rows

**What it is.** A trailing row written at export time, a row appended by a different system,
or a row that exists only because one slow tag updated.

**What it looks like.** A row where most mapped roles are empty.

**What it fakes.** *A critical invariant violation.* In one real export the engine was built against, a single trailing
row with every field empty produced a CRITICAL "discharge pressure below suction pressure"
finding that outranked everything real in the report, because `NaN > NaN` is `False` in pandas
rather than null.

**Caught by.** `_gate_invalid_rows` blanks rows below half-populated before any non-DQ check,
`dq_partial_rows` reports them, and `_operand_mask` in `relational.py` derives evaluability
from the operands rather than from the comparison result.

## 11. Join duplicates and asset suffix collisions

**What it is.** A wide export built by joining one frame per tag produces `Foo` and `Foo (2)`
when a tag matches twice, or when the same tag is pulled under two asset suffixes.

**What it looks like.** Two columns with identical values and near-identical names.

**What it fakes.**
- *Double weight* in any correlation matrix, PCA or multivariate distance, because the
  duplicated variable counts twice.
- *A resolved tag map*, when in fact the resolver had to choose. The counter suffix is the
  only reliable tell: `Foo (2)` alongside `Foo`, in any naming convention, from any join.

**Caught by.** `dq_duplicate_series` reports exact duplicates. `resolve` refuses to guess when
a role matches multiple columns and reports the ambiguity rather than picking one.

## 12. Timestamp pathology

**What it is.** Duplicate stamps, out-of-order rows, DST transitions in local time, a
timezone change mid-export, unparseable strings, and cadence gaps from outages or from a
historian restart.

**What it looks like.** Usually nothing, until a diff goes negative or a groupby silently
drops rows.

**What it fakes.**
- *A step*, at a DST boundary, because an hour repeats or vanishes.
- *A negative rate of change*, from an out-of-order row.
- *A lost window*, when duplicate stamps collapse in a resample.

**Caught by.** `dq_timestamp_regularity`. Unparseable timestamps become `NaT` and stay in the
frame so the check can see them; nothing is dropped silently.

## 13. Transmitter range change and recalibration

**What it is.** A 0 to 1000 psi transmitter replaced with a 0 to 1500, a span or zero
adjustment, or a calculation constant edited in the DCS.

**What it looks like.** A step in level, or a step in noise amplitude, with no process cause.

**What it fakes.** *A process event*, and a very convincing one, because it is a genuine step
in a genuine measurement.

**Caught by.** `stat_changepoint`, which then reports it as a step and says explicitly that
steps come from discrete causes including instrument recalibration, with `next_step` pointing
at the operations log and SCADA change record before any equipment explanation. A step on one
tag alone is reported as `unconfirmed` and flagged as more consistent with an instrument fault
than a process event, which is exactly this case.

## 14. Units and scaling changes

**What it is.** A tag switched from BPD to BPH, psig to psia, degF to degC, or a scaling
factor changed in the historian's tag configuration.

**What it looks like.** A step by a clean ratio: 24, 60, 14.7 offset, or the F-to-C affine
map.

**What it fakes.** A dramatic process change. A psig-to-psia switch on a low-pressure suction
tag is a 14.7 psi step that can flip an inequality invariant.

**Caught by.** Hard limits usually, `stat_changepoint` otherwise. The ratio being a clean
conversion factor is the tell, and no check tests for that. It is worth adding.

## 15. Backfill and late-arriving data

**What it is.** Data written into the archive after the fact, from a manual entry, a lab LIMS
sync, or a buffered interface recovering after a comms outage.

**What it looks like.** A region that was empty in one export and populated in the next.

**What it fakes.** *Irreproducibility.* An analysis run twice against the same query returns
different answers, which reads as a code bug. It also means a gap that `dq_timestamp_regularity`
reported may not be a gap at all.

**Caught by.** Nothing. The mitigation is to record the export timestamp with the analysis,
which the report header does.

## 16. Manually entered and constant tags

**What it is.** A setpoint, a dose rate, or a property typed in once and never changed.

**What it looks like.** A constant.

**What it fakes.** *A ruled-out confounder.* In one real export the engine was built against, `dra_ppm` is constant at
10 for all 350 samples. It is the primary confounder for residual excursions, so every failure
mode that requires "DRA rate unchanged" is trivially satisfied and nothing is actually
excluded. The correct reading is not "DRA is not the cause" but "DRA cannot be evaluated from
this dataset".

**Caught by.** `dq_flatline`, and the card records it in the role's `source`. The confounder
logic in `sme_signature_match` treats an unexcludable confounder as a reason to emit
`kind: candidate` with reduced confidence rather than a defect.

## 17. Derived tags computed from stale inputs

**What it is.** A calculated tag in the source system (a theoretical pressure drop, a
corrected flow, an efficiency) that updates on its own schedule and may use an input that has
not refreshed.

**What it looks like.** A derived value that is internally consistent but disagrees with a
recomputation from its own inputs.

**What it fakes.** *A model error.* The model may be fine; the inputs were stale when it ran.

**Caught by.** `rel_identity`. In one real export the engine was built against, `Residual = Actual - Theo` holds
exactly across all 350 samples, which is what makes everything built on the residual rest on a
checked identity rather than an assumption. When an identity does not hold, that is the
finding, and it is a source-system finding rather than a process one.

## 18. Event and detector columns

**What it is.** A pre-computed flag shipped alongside the data, usually thresholded by eye.

**What it looks like.** A 0/1 column.

**What it fakes.** *Prior analysis.* A flag in the dataset implies someone has already
validated it. In one real export the engine was built against, `Events - Positive Rate of Change` fires on 230 of 351
samples, 66 percent, because it is thresholded at zero and roughly half the increments of any
mean-reverting series are positive.

**Caught by.** `stat_detector_firing_rate`, which audits base rate before anything trusts the
flag.

---

## Order of operations

1. Establish the time axis is sound.
2. Establish each column is a measurement: not frozen, not held, not railed, not a duplicate,
   not a quality code.
3. Only then compare anything to anything.

Inverting steps 2 and 3 is the single most common way a time series analysis produces a
confident answer about an export bug.
