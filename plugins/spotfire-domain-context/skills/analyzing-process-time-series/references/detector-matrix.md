# Detector matrix

Which method answers which question, and how each one lies. Read the failure mode column
before trusting a finding: every detector here has a regime in which it is confidently wrong,
and knowing which one you are in is most of the analysis.

## Pick the method from the question

| The question | Method | Not this |
|---|---|---|
| Is the number physically possible | Hard limit against the card | A z-score. A physically impossible value is a data fault, not an outlier |
| Is the unit running outside its usual envelope | `normal` band, regime-conditioned | A global sigma rule; the envelope is a function of throughput |
| Did something change abruptly | CUSUM on the regime-normalised signal | A rolling mean difference, which smears the boundary |
| Is something degrading slowly | Slope with regime as a fixed effect, autocorrelation-adjusted | Within-regime z-scoring, which absorbs the drift |
| Is the model any good | Residual bias plus residual trend | Residual variance alone; a biased model can be very repeatable |
| Is the relationship between two tags intact | Invariant, power-law exponent, or rank correlation | Pearson correlation, which is a linearity test wearing a relationship costume |
| Which fault is it | Multi-tag signature match with confounders excluded | Any single-tag threshold |
| Is the tag real | Flatline, rail, zero-order hold, duplicate-series checks | Anything downstream; these gate everything |

## The check battery

Category order is fixed: `data_quality`, `physical`, `relational`, `statistical`, `sme`.
A finding produced on a broken column is worse than no finding, so data quality runs first
and everything after it inherits its verdict.

### data_quality

| Check | Question | Method | Fires when | How it lies |
|---|---|---|---|---|
| `dq_timestamp_regularity` | Is the time axis trustworthy | Diff of the index; count unparseable, duplicate, out-of-order stamps and cadence gaps | Any of the above | A regular cadence proves nothing about content. A resampled export looks perfect |
| `dq_missing` | Is a required role populated | Null fraction per required role, plus values that failed numeric coercion | Role absent, or more than 5 percent null | Says nothing about whether the populated values are real |
| `dq_partial_rows` | Are there export artifacts | Row-wise populated fraction below half | Any such row | A row that is half-populated by design (a lab row) reads as an artifact. Check the cadence first |
| `dq_duplicate_series` | Is a column a join artifact | Exact equality against a mapped role | Identical series under a second name | Two genuinely redundant transmitters are also identical. That is a real finding about instrumentation, not a fake one |
| `dq_flatline` | Is the sensor frozen | Longest run of an identical value on a `sensor` or `calculated` role that is not a CV | A run of at least max(5, 3 percent of samples) | A genuinely steady process on a coarse transmitter looks frozen. The schema has no quantisation field yet to separate the two, so read the held value against the transmitter resolution yourself |
| `dq_zero_order_hold` | Is a lab value stale | Distinct-value count and longest hold against the declared cadence | Updates far less often than declared, **or far more often** | The "far more often" branch is the important one: a `lab` role that changes every sample is modelled, not assayed, so it is not independent evidence |
| `dq_rail_saturation` | Are the extremes measurements | Repeated exact min or max in an otherwise continuous signal | Pile-up beyond 3x the typical value multiplicity | A coarsely quantised signal piles up at every value, not just the ends. The distinct-fraction gate at 0.5 handles that; below it, `dq_flatline` owns the signal |

Rails are detected once in `prep`, not inside the check, so `phys_range` excludes the same
samples. Two definitions of "is this a measurement" is how twelve clipped samples get reported
twice under two different explanations.

### physical

| Check | Question | Method | Fires when | How it lies |
|---|---|---|---|---|
| `phys_range` (hard limits) | Is the value possible | Card `limits` | Any excursion, always `critical` | Almost never wrong, which is why it is critical. If it fires often, the tag map is wrong, not the plant |
| `phys_range` (descriptive band) | Is the unit outside its usual envelope | Card `normal` with `band_type: descriptive` | Excursion fraction above tolerance | **Severity is not monotonic in excursion fraction.** Above roughly 20 percent the finding is about the card, not the plant, so it de-escalates to `low` |
| `phys_range` (normative band) | Is the unit off-spec, or the model wrong | Card `normal` with `band_type: normative` | Any material excursion | Inverts the rule above: a high excursion rate is the finding and the band must never be widened to fit the data |

### relational

| Check | Question | Method | Fires when | How it lies |
|---|---|---|---|---|
| `rel_identity` | Does a definitional identity or a balance hold | Elementwise difference against a tolerance (`balance` invariants use a wider one) | Any material break | A break means the source-system formula changed or columns are misaligned. It is almost never a process finding |
| `rel_inequality` | Does the required ordering hold | Elementwise comparison, gated by `_operand_mask` | Any evaluable violation | **`NaN > NaN` is `False` in pandas.** Evaluability must come from the operands. Read off the result, every blanked row becomes a critical violation |
| `rel_power_law` | Is the exponent right | OLS in log-log space | Fitted `n` outside the card's band with adequate R-squared | Log-log OLS is sensitive to the low end of the range. A narrow flow range gives a badly determined exponent with a deceptively high R-squared |
| `rel_monotonic` | Does the relationship have the right sign | Spearman rank correlation | Sign opposed to the card, with adequate magnitude | Monotonicity often holds only under a condition the data cannot see. That is what `requires_roles` is for: a pump H-Q curve falls with flow only at constant speed and fixed pump count |

Every relational check reports an invariant it cannot evaluate (a missing operand, an
expression form it does not parse, too few samples) as `not_evaluated` rather than skipping
it. `requires_roles` turns an unevaluable invariant into a visible coverage gap
(`kind: not_evaluated`) rather than a confident wrong violation. A mainline station that ramps
a VFD to push more barrels shows head **rising** with flow, and an unconditioned
`head_flow_monotonic` reports that as a fault every time.

### statistical

| Check | Question | Method | Fires when | How it lies |
|---|---|---|---|---|
| `stat_residual_bias` | Is the model centred | Mean against the card band, SE inflated by `sqrt(n/n_eff)` | Mean outside the band | Assumes AR(1). For a residual with seasonal structure the correction is too small and the t-statistic is still optimistic |
| `stat_regime_drift` | Is something degrading | `y ~ 1 + slope*t + regime dummies` via `lstsq`, autocorrelation-adjusted SE | CI excludes zero **and** total change exceeds 1 residual sd | A slope fitted across a regime change that is not in the dummy set is a step masquerading as a trend. Run `stat_changepoint` and read them together |
| `stat_changepoint` | Was there a step | CUSUM on the regime-normalised signal, shift measured in pooled within-segment sd, clustered across roles | Largest inter-segment shift above 2.0 pooled sd | **Measured against the whole series' sd, a clean two-level step is capped at exactly 2.0** because the series sd grows with the step. Any threshold near 2.0 measured that way rejects the most obvious steps in the data |
| `stat_detector_firing_rate` | Is an existing event flag informative | Firing rate against sample count | Above 20 percent, above 10 percent, or exactly zero | A legitimately high-duty condition (a unit that genuinely runs off-spec half the year) also fires often. The finding is still correct: the flag cannot discriminate |

**CUSUM detection lag.** Detection comes only after evidence accumulates, and the average run
length scales roughly as `h / (delta - k)`. Tags responding to one event trip days apart,
biggest mover first. Cluster on a window at least as wide as the expected lag (default 10
samples) or you resplit the event you just merged. The per-role `detected_at` map in the
finding's statistic exists so a reader can see the lag rather than mistake it for a sequence
of causes.

### sme

| Check | Question | Method | Fires when | How it lies |
|---|---|---|---|---|
| `sme_signature_match` | Which failure mode fits | Score the card's multi-role signature against observed directions, then exclude confounders | Score above threshold with at least two roles agreeing | Emits `kind: candidate`, never `defect`. A signature is a hypothesis. If its confounders cannot be excluded from the available tags, the honest answer is "possible and unconfirmable", and the finding says so |
| `sme_head_deficit_at_matched_flow` | Is the pump wearing | Theil-Sen slope of head **within** flow bands, agreement required across bands | Consistent deficit across bands | Compared across flow, a pump that simply ran harder this year looks worn. Within-band comparison is the whole point. If the bands disagree, that inconsistency is itself the finding, and it must not be reported as health |

## Methods deliberately not used

Recorded so the gap is visible rather than accidental. The runtime constraint is numpy,
pandas and pyyaml (scipy optional), because the library has to execute inside a Spotfire
Python data function.

| Method | Would answer | Why it is out |
|---|---|---|
| PELT / binary segmentation | Exact changepoint boundaries with no detection lag | Needs `ruptures` or a careful reimplementation. CUSUM plus clustering is adequate for daily data; it would not be for one-minute data |
| PCA / T-squared and Q statistics | Multivariate excursion across many correlated tags at once | Needs sklearn. Also produces a score with no physical interpretation, which conflicts with the requirement that a finding carry a next step |
| Autoencoder, isolation forest, LSTM | Unlabelled anomaly scores | Same interpretability objection, plus a training-set requirement that a single-asset export does not meet. A reconstruction error is not a finding |
| ARIMA / state-space forecasting | Prediction intervals for a tag | Needs statsmodels. The card's physics model already provides the expectation, which is more defensible than a fitted one |
| Newey-West standard errors | Correct inference under general autocorrelation | AR(1) is the reported approximation because `se_inflation` is one number an engineer can check. The approximation is recorded as a limitation |
| Benjamini-Hochberg FDR | Multiplicity control across a battery of hundreds of implicit tests | Effect-size gating is used instead, because a corrected p-value is not actionable at a pump. This is a real gap |

## Choosing a threshold

1. Compute the base rate first. If the detector would fire on more than 20 percent of samples,
   it is not a detector, whatever it is measuring.
2. State the units the effect size is in, and make sure they are the units the noise lives in.
   Pooled within-segment sd for a step; residual sd for a trend; never the raw series sd.
3. Check the threshold against a synthetic case where you know the answer. The 2.0 sd
   changepoint cap was found by a test failing, not by reading the code.
4. Write the threshold into the finding's `statistic`. A reader who disagrees with it can then
   see it rather than guess at it.
