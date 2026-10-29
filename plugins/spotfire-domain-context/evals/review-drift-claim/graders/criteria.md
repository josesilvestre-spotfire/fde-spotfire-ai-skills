---
type: llm
weight: 1
---

Grade the response and the file `drift_check.py`. Pass when at least 6 of the 8 criteria
hold and criteria 1 and 2 both hold.

1. **Regime handling.** States that z-scoring within flow bands subtracts each band's mean
   and absorbs the drift because band membership correlates with time (throughput rose),
   and replaces it with a regression that carries flow band as a fixed effect (band dummy
   variables) alongside time, or an equivalent within-regime comparison that does not
   demean by band.
2. **Autocorrelation.** States that daily process data is autocorrelated so the ordinary
   standard error overstates significance, and corrects it (effective sample size such as
   `n_eff = n(1 - r1)/(1 + r1)` with the standard error inflated by `sqrt(n / n_eff)`,
   Newey-West, or block methods).
3. **Lab staleness.** Identifies that a weekly lab viscosity is held constant between
   assays, so the predicted drop and the residual carry a sawtooth or step at each assay that
   is a model artifact, not a line condition.
4. **Confounders.** Names at least two benign explanations to exclude before calling wax:
   seasonal temperature (viscosity), a drag reducer dose change or outage, a batch or crude
   slate change, a throughput or operating regime change.
5. **Data quality first.** Recommends checking for at least two historian artifacts before
   trending: frozen or flatlined tags, transmitter rails or clamps, duplicated columns,
   partial or blank rows, quality codes or gaps, a constant drag reducer tag that cannot
   exclude anything.
6. **Trend is not a diagnosis.** Says a rising residual alone does not establish wax: it
   asks for corroborating evidence (multi-tag signature, onset over weeks rather than a
   step, temperature against cloud point, pig run records or another field check) and
   mentions instrument drift or model bias as alternatives.
7. **Code.** `drift_check.py` exists, imports only numpy and pandas (no statsmodels,
   scikit-learn or scipy), fits the residual against time with flow-band dummies (for
   example with `np.linalg.lstsq`), and widens the standard error for autocorrelation
   before computing the confidence interval.
8. **No invented facts.** Does not state plant-specific numbers (cloud point, design
   roughness, a "typical" wax rate) as if they were known for this line.
