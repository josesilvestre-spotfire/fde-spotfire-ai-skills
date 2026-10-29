# Time series analysis: flow-segment / (single asset)

- Unit class: flow_segment | persona: example_analyst | pack: example | calibration: example-segment-2026H1
- Samples: 401 | period: 2026-01-01 00:00:00 to 2026-01-17 16:00:00 | 1 row(s) blanked as partial
- Roles resolved: 9 of 9
- Operating regimes: 6
- Checks run: 16
- Findings: 4 high, 7 medium, 1 low | 8 candidate diagnosis(es) | 1 not evaluated

## Tag resolution warnings

- `flow` matched multiple columns: ['FI-1004.PV', 'FI-1004.PV (2)']; used `FI-1004.PV`

## Findings

### [HIGH] Role 'additive_ppm' holds a constant value for up to 400 consecutive samples.
check `dq_flatline` | confidence **unconfirmed** | roles `additive_ppm`

A measured signal that does not move is usually a frozen transmitter, a failed poll holding last-good, or a manually entered constant. Its variance is fake, so it will look like the most stable and most trustworthy tag in the dataset while carrying no information.

- longest_run: 400
- held_value: 12
- fraction_in_long_runs: 1
- min_run_threshold: 12

Next step: Confirm whether 'additive_ppm' is genuinely instrumented or is a constant entered upstream.

Source: Historian deadband/exception compression and its effect on derived statistics (Thornhill, Choudhury & Shah, J.Process Control 2004, 'The impact of compression on data-driven process analyses')

### [HIGH] 'residual_pct' is outside its specified band [-5, 5] on 28.5% of samples (observed -1.144 to 10.34).
check `phys_range` | confidence **unconfirmed** | roles `residual_pct` | window 2026-01-12 13:00:00 to 2026-01-17 15:00:00

This band is a specification, not a description of how this asset happens to run, so a high excursion rate does not mean the band needs widening. It means the unit spends that fraction of its time off-spec, or the model behind the band is wrong.

- outside_fraction: 0.285
- normal: [-5, 5]
- clamped_samples_excluded: 0
- observed_min: -1.144
- observed_max: 10.34
- p01: -0.7035
- p99: 9.854
- suggested_band: [-0.7035, 9.854]
- band_type: normative

Next step: Do not widen this band. Establish why 'residual_pct' sits outside it: for a model residual, reconcile the model; for a process spec, treat the excursion time as the finding.

Source: A MODEL QUALITY TARGET, not a description of any asset: a correctly tuned friction model reproduces a measured differential to within a few percent. Exceeding it means the model is wrong or the segment is restricted. The band must not be widened to fit the data.


### [HIGH] Detector column 'Events - Positive Rate of Change' fires on 50% of samples (201 of 400).
check `stat_detector_firing_rate` | confidence **unconfirmed**

At this rate the flag carries almost no information: it is close to the base rate of the signal itself, so it cannot separate normal from abnormal. A rate-of-change detector thresholded at zero fires on roughly half of all samples by construction, because half of the changes in any mean-reverting series are positive.

- firing_rate: 0.502
- firing_samples: 201
- valid_samples: 400
- event_runs: 126

Next step: Threshold on the magnitude of the change relative to its own regime-conditioned distribution, not on its sign. Target a firing rate consistent with the expected event base rate, typically low single-digit percent.

Source: Base-rate discipline in alarm design (EEMUA 191; ISA-18.2 alarm rationalisation)

### [HIGH] residual is rising at +4.32 kPa/month after removing the operating-regime effect (t=+16.1, +8.9 residual sd over 17 days).
check `stat_regime_drift` | confidence **unconfirmed** | roles `residual` | window 2026-01-01 00:00:00 to 2026-01-17 16:00:00

Operating regime is carried in the model as a fixed effect rather than removed by within-band z-scoring, so this slope is not an artifact of the unit running harder or softer over the period, and it has not been absorbed by the regime either. That makes it a genuine change in the equipment, the fluid, or the instrument.

- slope_per_month: 4.32
- ci95_per_month: [3.793, 4.847]
- t_statistic: 16.07
- total_change: 2.394
- total_change_residual_sd: 8.92
- regime_bands_in_model: 6
- samples: 400
- lag1_autocorr: 0.8
- se_inflation_for_autocorr: 3

Next step: Match the onset against the card's failure modes; a slope sustained over weeks points to deposition or wear rather than a discrete event.

Source: Effective sample size under autocorrelation, n_eff = n(1-r1)/(1+r1) (Bayley & Hammersley 1946; Wilks, Statistical Methods in the Atmospheric Sciences)

### [MEDIUM] 1 row(s) have fewer than half of the expected measurements populated.
check `dq_partial_rows` | confidence **unconfirmed** | window 2026-01-17 16:00:00 to 2026-01-17 16:00:00

Near-empty rows are usually snapshot or append artifacts rather than real samples. They are invisible in a line chart but they corrupt last-value reads, diffs at the boundary, and any 'current state' summary.

- partial_rows: 1
- timestamps: [2026-01-17 16:00:00]
- min_fill_fraction: 0
- action: blanked before all non-data-quality checks

Next step: Confirm these are export artifacts and filter them before analysis.

### [MEDIUM] Role 'temperature' is pinned at min 20 on 6 sample(s) and max 36 on 6 sample(s), against 322 distinct values overall.
check `dq_rail_saturation` | confidence **unconfirmed** | roles `temperature`

A continuous measurement does not repeat its own extreme this often. The value is clipped, either by the transmitter range or by a clamp applied upstream to keep a model input in its valid domain. The true excursions are censored, so the peak is understated and the variance is compressed.

- rails: [{end: min, value: 20, samples: 6}, {end: max, value: 36, samples: 6}]
- pinned_samples: 12
- pinned_fraction: 0.03
- distinct_fraction: 0.805
- median_value_multiplicity: 1
- unclamped_range: [21.23, 34.05]

Next step: Do not calibrate the 'temperature' band from the observed min and max; use the unclamped interior instead. Confirm the transmitter span and find the clamp in the source calculation.

Source: Historian deadband/exception compression and its effect on derived statistics (Thornhill, Choudhury & Shah, J.Process Control 2004, 'The impact of compression on data-driven process analyses')

### [MEDIUM] Lab role 'density' updates only every ~200.0 samples (2 distinct updates over 400 samples) and is held constant between assays.
check `dq_zero_order_hold` | confidence **unconfirmed** | roles `density`

Lab values are zero-order-held between samples. Anything computed from them inherits that staleness: the modelled value is right on assay day and progressively wrong until the next one, which puts a sawtooth into the residual that resets at each assay. That sawtooth is a model artifact and must not be read as process behaviour.

- updates: 2
- samples: 400
- effective_update_interval_samples: 200
- longest_hold_samples: 168
- declared_update_interval: 168h

Next step: Interpolate lab properties against a measured driver (temperature) instead of holding them, or restrict residual trending to assay days.

Source: Zero-order-hold artifact from merging lab cadence into a SCADA frame

### [MEDIUM] Step change at 2026-01-07 05:00:00 across 1 role(s) (temperature), largest 2.1 sd on temperature.
check `stat_changepoint` | confidence **unconfirmed** | roles `temperature` | window 2026-01-07 05:00:00 to 2026-01-07 05:00:00

A step, not a ramp. Steps come from discrete causes: a valve position, an injection change, a batch interface, a control change, or an instrument recalibration. Deposition and wear do not step. Only one tag moves, which is more consistent with an instrument fault than a process event.

- roles_stepping: {temperature: 2.12}
- detected_at: {temperature: 2026-01-07 05:00:00}
- lead_role: temperature
- largest_shift_sd: 2.12
- cluster_span_samples: 0
- shift_measured_against: pooled within-segment sd
- min_shift_threshold_sd: 2

Next step: Pull the operations log and SCADA change record for this timestamp before considering any equipment explanation.

Source: CUSUM change detection (Page, Biometrika 1954)

### [MEDIUM] Step change at 2026-01-09 18:00:00 across 1 role(s) (residual), largest 3.5 sd on residual.
check `stat_changepoint` | confidence **unconfirmed** | roles `residual` | window 2026-01-09 18:00:00 to 2026-01-09 18:00:00

A step, not a ramp. Steps come from discrete causes: a valve position, an injection change, a batch interface, a control change, or an instrument recalibration. Deposition and wear do not step. Only one tag moves, which is more consistent with an instrument fault than a process event.

- roles_stepping: {residual: 3.52}
- detected_at: {residual: 2026-01-09 18:00:00}
- lead_role: residual
- largest_shift_sd: 3.52
- cluster_span_samples: 0
- shift_measured_against: pooled within-segment sd
- min_shift_threshold_sd: 2

Next step: Pull the operations log and SCADA change record for this timestamp before considering any equipment explanation.

Source: CUSUM change detection (Page, Biometrika 1954)

### [MEDIUM] measured_dp is rising at +4.31 kPa/month after removing the operating-regime effect (t=+5.5, +1.1 residual sd over 17 days).
check `stat_regime_drift` | confidence **unconfirmed** | roles `measured_dp` | window 2026-01-01 00:00:00 to 2026-01-17 16:00:00

Operating regime is carried in the model as a fixed effect rather than removed by within-band z-scoring, so this slope is not an artifact of the unit running harder or softer over the period, and it has not been absorbed by the regime either. That makes it a genuine change in the equipment, the fluid, or the instrument.

- slope_per_month: 4.307
- ci95_per_month: [2.776, 5.839]
- t_statistic: 5.51
- total_change: 2.387
- total_change_residual_sd: 1.14
- regime_bands_in_model: 6
- samples: 400
- lag1_autocorr: 0.115
- se_inflation_for_autocorr: 1.12

Next step: Match the onset against the card's failure modes; a slope sustained over weeks points to deposition or wear rather than a discrete event.

Source: Effective sample size under autocorrelation, n_eff = n(1-r1)/(1+r1) (Bayley & Hammersley 1946; Wilks, Statistical Methods in the Atmospheric Sciences)

### [MEDIUM] residual_pct is biased at +3.50 (expected within [-3.0, 3.0]), t=2.7 on 6 effective samples.
check `stat_residual_bias` | confidence **unconfirmed** | roles `residual_pct`

A model residual with a persistent offset means the model is mis-calibrated, not that the process is drifting. Until the bias is explained, every threshold set on this residual inherits it, and the magnitude of any excursion is measured from the wrong zero.

- mean: 3.502
- band: [-3, 3]
- t_statistic: 2.72
- n: 400
- n_effective: 5.6
- lag1_autocorr: 0.973
- sem_autocorr_adjusted: 1.287

Next step: Reconcile the constant terms in the model first: line roughness, an omitted static-head or elevation term, and instrument zero offsets. Only then trend it.

Source: A calibrated model is unbiased. Persistent bias is an untuned coefficient, an omitted term, or a real restriction. | Effective sample size under autocorrelation, n_eff = n(1-r1)/(1+r1) (Bayley & Hammersley 1946; Wilks, Statistical Methods in the Atmospheric Sciences)

### [LOW] Column 'FI-1004.PV (2)' duplicates role 'flow' (identical values).
check `dq_duplicate_series` | confidence **unconfirmed** | roles `flow`

A join artifact. Harmless if identical, but it doubles the role in any 'all columns' operation such as correlation matrices or PCA, inflating that variable's weight.

- primary: FI-1004.PV
- duplicate: FI-1004.PV (2)
- identical: True
- compared_samples: 400

Next step: Drop the duplicate at the data-prep step and fix the join that created it.

## Candidate diagnoses

Signature matches against the unit card. These are hypotheses, not conclusions: read the confounder status on each before acting.

### [CANDIDATE/MEDIUM] Signature consistent with 'Pressure transmitter calibration drift' over 2026-01-17 10:00:00 to 2026-01-17 12:00:00 (match 67%, confidence corroborated).
check `sme_signature_match` | confidence **corroborated** | roles `flow`, `inlet_pressure`, `residual` | window 2026-01-17 10:00:00 to 2026-01-17 12:00:00

67% of the card signature for 'Pressure transmitter calibration drift' is present over this window (residual=up, inlet_pressure=unchanged, flow=unchanged). This is a candidate, not a diagnosis: the same window also matches restriction (75%) [declared differential].

- failure_mode: instrument_drift
- match_score: 0.67
- anchor_role: residual
- peak_z: 3.79
- window_samples: 3
- card_onset: weeks
- competing_modes: {restriction: 0.75}
- matched_roles: [flow, residual]

Confounders:
- sample_staleness: ruled out
- flow_regime_shift: ruled out

Next step: Compare the transmitter against a calibrated reference; pull the last calibration date.

Source: Synthetic example; instrument drift as a differential for a real degradation

### [CANDIDATE/MEDIUM] Signature consistent with 'Progressive restriction of the segment bore' over 2026-01-17 10:00:00 to 2026-01-17 12:00:00 (match 75%, confidence unconfirmed).
check `sme_signature_match` | confidence **unconfirmed** | roles `measured_dp`, `predicted_dp`, `residual`, `temperature` | window 2026-01-17 10:00:00 to 2026-01-17 12:00:00

75% of the card signature for 'Progressive restriction of the segment bore' is present over this window (residual=up, measured_dp=up, predicted_dp=unchanged, temperature=flat). This is a candidate, not a diagnosis: not ruled out: temperature_effect (density shifted more than 1 sd in this window and could produce the same effect); the same window also matches instrument_drift (67%) [declared differential].

- failure_mode: restriction
- match_score: 0.75
- anchor_role: residual
- peak_z: 3.79
- window_samples: 3
- card_onset: weeks
- competing_modes: {instrument_drift: 0.67}
- matched_roles: [measured_dp, predicted_dp, residual]

Confounders:
- temperature_effect: NOT RULED OUT
- flow_regime_shift: ruled out
- additive_change: ruled out

Next step: Inspect or pig the segment and compare the residual before and after.

Source: Synthetic example; a deposition-style degradation with a multi-role signature

### [CANDIDATE/LOW] Signature consistent with 'Pressure transmitter calibration drift' over 2026-01-16 22:00:00 to 2026-01-16 22:00:00 (match 100%, confidence unconfirmed).
check `sme_signature_match` | confidence **unconfirmed** | roles `flow`, `inlet_pressure`, `residual` | window 2026-01-16 22:00:00 to 2026-01-16 22:00:00

100% of the card signature for 'Pressure transmitter calibration drift' is present over this window (residual=up, inlet_pressure=up, flow=flat). This is a candidate, not a diagnosis: card onset is 'weeks' but the excursion lasts only 1 sample(s).

- failure_mode: instrument_drift
- match_score: 1
- anchor_role: inlet_pressure
- peak_z: 3.27
- window_samples: 1
- card_onset: weeks
- competing_modes: {}
- matched_roles: [flow, inlet_pressure, residual]

Confounders:
- sample_staleness: ruled out
- flow_regime_shift: ruled out

Next step: Compare the transmitter against a calibrated reference; pull the last calibration date.

Source: Synthetic example; instrument drift as a differential for a real degradation

### [CANDIDATE/LOW] Signature consistent with 'Pressure transmitter calibration drift' over 2026-01-09 05:00:00 to 2026-01-09 05:00:00 (match 67%, confidence unconfirmed).
check `sme_signature_match` | confidence **unconfirmed** | roles `flow`, `inlet_pressure`, `residual` | window 2026-01-09 05:00:00 to 2026-01-09 05:00:00

67% of the card signature for 'Pressure transmitter calibration drift' is present over this window (residual=flat, inlet_pressure=up, flow=unchanged). This is a candidate, not a diagnosis: card onset is 'weeks' but the excursion lasts only 1 sample(s).

- failure_mode: instrument_drift
- match_score: 0.67
- anchor_role: inlet_pressure
- peak_z: 3.09
- window_samples: 1
- card_onset: weeks
- competing_modes: {}
- matched_roles: [flow, inlet_pressure]

Confounders:
- sample_staleness: ruled out
- flow_regime_shift: ruled out

Next step: Compare the transmitter against a calibrated reference; pull the last calibration date.

Source: Synthetic example; instrument drift as a differential for a real degradation

### [CANDIDATE/LOW] Signature consistent with 'Pressure transmitter calibration drift' over 2026-01-15 09:00:00 to 2026-01-15 09:00:00 (match 67%, confidence unconfirmed).
check `sme_signature_match` | confidence **unconfirmed** | roles `flow`, `inlet_pressure`, `residual` | window 2026-01-15 09:00:00 to 2026-01-15 09:00:00

67% of the card signature for 'Pressure transmitter calibration drift' is present over this window (residual=unchanged, inlet_pressure=up, flow=unchanged). This is a candidate, not a diagnosis: card onset is 'weeks' but the excursion lasts only 1 sample(s) and arrives as a 4.0 sd step.

- failure_mode: instrument_drift
- match_score: 0.67
- anchor_role: temperature
- peak_z: 3.02
- window_samples: 1
- card_onset: weeks
- competing_modes: {}
- matched_roles: [flow, inlet_pressure]

Confounders:
- sample_staleness: ruled out
- flow_regime_shift: ruled out

Next step: Compare the transmitter against a calibrated reference; pull the last calibration date.

Source: Synthetic example; instrument drift as a differential for a real degradation

### [CANDIDATE/LOW] Signature consistent with 'Pressure transmitter calibration drift' over 2026-01-16 14:00:00 to 2026-01-16 14:00:00 (match 100%, confidence unconfirmed).
check `sme_signature_match` | confidence **unconfirmed** | roles `flow`, `inlet_pressure`, `residual` | window 2026-01-16 14:00:00 to 2026-01-16 14:00:00

100% of the card signature for 'Pressure transmitter calibration drift' is present over this window (residual=up, inlet_pressure=up, flow=flat). This is a candidate, not a diagnosis: card onset is 'weeks' but the excursion lasts only 1 sample(s).

- failure_mode: instrument_drift
- match_score: 1
- anchor_role: inlet_pressure
- peak_z: 2.84
- window_samples: 1
- card_onset: weeks
- competing_modes: {}
- matched_roles: [flow, inlet_pressure, residual]

Confounders:
- sample_staleness: ruled out
- flow_regime_shift: ruled out

Next step: Compare the transmitter against a calibrated reference; pull the last calibration date.

Source: Synthetic example; instrument drift as a differential for a real degradation

### [CANDIDATE/LOW] Signature consistent with 'Progressive restriction of the segment bore' over 2026-01-17 09:00:00 to 2026-01-17 09:00:00 (match 75%, confidence unconfirmed).
check `sme_signature_match` | confidence **unconfirmed** | roles `measured_dp`, `predicted_dp`, `residual`, `temperature` | window 2026-01-17 09:00:00 to 2026-01-17 09:00:00

75% of the card signature for 'Progressive restriction of the segment bore' is present over this window (residual=up, measured_dp=unchanged, predicted_dp=unchanged, temperature=sharp_down). This is a candidate, not a diagnosis: not ruled out: temperature_effect (temperature, density shifted more than 1 sd in this window and could produce the same effect); card onset is 'weeks' but the excursion lasts only 1 sample(s); the same window also matches instrument_drift (67%) [declared differential].

- failure_mode: restriction
- match_score: 0.75
- anchor_role: temperature
- peak_z: 2.71
- window_samples: 1
- card_onset: weeks
- competing_modes: {instrument_drift: 0.67}
- matched_roles: [predicted_dp, residual, temperature]

Confounders:
- temperature_effect: NOT RULED OUT
- flow_regime_shift: ruled out
- additive_change: ruled out

Next step: Inspect or pig the segment and compare the residual before and after.

Source: Synthetic example; a deposition-style degradation with a multi-role signature

### [CANDIDATE/LOW] Signature consistent with 'Pressure transmitter calibration drift' over 2026-01-17 09:00:00 to 2026-01-17 09:00:00 (match 67%, confidence unconfirmed).
check `sme_signature_match` | confidence **unconfirmed** | roles `flow`, `inlet_pressure`, `residual` | window 2026-01-17 09:00:00 to 2026-01-17 09:00:00

67% of the card signature for 'Pressure transmitter calibration drift' is present over this window (residual=up, inlet_pressure=unchanged, flow=unchanged). This is a candidate, not a diagnosis: card onset is 'weeks' but the excursion lasts only 1 sample(s); the same window also matches restriction (75%) [declared differential].

- failure_mode: instrument_drift
- match_score: 0.67
- anchor_role: temperature
- peak_z: 2.71
- window_samples: 1
- card_onset: weeks
- competing_modes: {restriction: 0.75}
- matched_roles: [flow, residual]

Confounders:
- sample_staleness: ruled out
- flow_regime_shift: ruled out

Next step: Compare the transmitter against a calibrated reference; pull the last calibration date.

Source: Synthetic example; instrument drift as a differential for a real degradation

## Not evaluated

These checks could not run against this dataset. They are coverage gaps, not clean bills of health.

- Invariant 'efficiency_at_reference' was not evaluated: it requires pump_speed, which is not in this dataset.

## Verified as healthy

- Invariant 'residual_identity' holds across all 400 samples.
- Invariant 'flow_drops_pressure' (inlet_pressure > outlet_pressure) holds across all 400 evaluable samples.
- measured_dp scales as flow^1.88 (expected 2.0), consistent with the card.
