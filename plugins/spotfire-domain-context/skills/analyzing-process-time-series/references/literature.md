# Literature

The citations behind every rule, threshold and method in `tssme`. A `source` string in the
code or in a unit card should resolve to an entry here.

**Verification status** is recorded per entry because the skill's own rule is that an
unsourced or unverified bound must say so rather than look authoritative:

- `verified` The work exists and says what is claimed of it.
- `chapter-approx` The work and the claim are right; the specific chapter or section number
  was written from memory and varies by edition. Cite the work, not the section.
- `UNVERIFIED` Needs checking against the actual document before it is relied on.

---

## 1. Inference on autocorrelated series

| Claim | Source | Status |
|---|---|---|
| `n_eff = n(1 - r1)/(1 + r1)` for an AR(1)-like series | Bayley, G.V. and Hammersley, J.M. (1946), "The 'Effective' Number of Independent Observations in an Autocorrelated Time Series", *Supplement to the JRSS* 8(2):184-197 | verified |
| Effective sample size in applied trend testing | Wilks, D.S., *Statistical Methods in the Atmospheric Sciences*, ch. 5 (autocorrelation and the effective sample size) | chapter-approx |
| Autocorrelation- and heteroskedasticity-consistent standard errors, the general case | Newey, W.K. and West, K.D. (1987), *Econometrica* 55(3):703-708 | verified |
| Reference text for the underlying theory | Hamilton, J.D. (1994), *Time Series Analysis*, Princeton University Press | verified |

`tssme` uses the AR(1) correction rather than Newey-West because it needs one number
(`se_inflation`) that can be reported in a finding and understood by a process engineer.
Newey-West is the better estimator when the residual autocorrelation is not approximately
AR(1); that is a known limitation, recorded in `method.md`.

**Why this matters more than anything else in the file.** A daily pipeline series with
`r1 = 0.9` has `n_eff` near `n/19`. The naive SEM therefore overstates significance by about
`sqrt(19)`, a factor above 4. Every "statistically significant degradation" produced without
this correction is suspect.

## 2. Trend estimation

| Claim | Source | Status |
|---|---|---|
| Robust slope from pairwise medians | Theil, H. (1950), *Proc. Koninklijke Nederlandse Akademie van Wetenschappen* 53; Sen, P.K. (1968), "Estimates of the Regression Coefficient Based on Kendall's Tau", *JASA* 63(324):1379-1389 | verified |
| Rank-based trend test, distribution free | Mann, H.B. (1945), *Econometrica* 13(3):245-259; Kendall, M.G. (1975), *Rank Correlation Methods* | verified |
| Seasonal-trend decomposition | Cleveland, R.B., Cleveland, W.S., McRae, J.E. and Terpenning, I. (1990), "STL: A Seasonal-Trend Decomposition Procedure Based on Loess", *Journal of Official Statistics* 6(1):3-73 | verified |

Theil-Sen is preferred over OLS wherever a single spike could dominate the fit, which in
historian data is always. It has a breakdown point near 29 percent.

**Fixed effects instead of within-group z-scoring.** This is standard panel-data practice
(Wooldridge, *Econometric Analysis of Cross Section and Panel Data*, ch. 10), not a `tssme`
invention. The point specific to process data is that operating regime and time are
correlated because throughput follows the season, so demeaning by regime removes the trend.

## 3. Change detection

| Claim | Source | Status |
|---|---|---|
| CUSUM | Page, E.S. (1954), "Continuous Inspection Schemes", *Biometrika* 41(1/2):100-115 | verified |
| CUSUM design, the `h` and `k` parameters, and average run length | Hawkins, D.M. and Olwell, D.H. (1998), *Cumulative Sum Charts and Charting for Quality Improvement*, Springer | verified |
| Control chart design in practice | Montgomery, D.C., *Introduction to Statistical Quality Control*, ch. 9 (CUSUM and EWMA) | chapter-approx |
| Exact multiple-changepoint segmentation in linear time | Killick, R., Fearnhead, P. and Eckley, I.A. (2012), "Optimal Detection of Changepoints With a Linear Computational Cost", *JASA* 107(500):1590-1598 | verified |

**Detection lag is the practical consequence.** CUSUM signals only once enough evidence has
accumulated, and the average run length to detection scales roughly as `h / (delta - k)` for
a shift of size `delta`. Two tags responding to one physical event trip days apart, the
bigger mover first. This is why `stat_changepoint` clusters on a window at least as wide as
the expected lag. PELT would give exact boundaries and remove most of the lag, and is the
obvious upgrade when a segmentation dependency becomes acceptable.

## 4. Robust statistics and multiplicity

| Claim | Source | Status |
|---|---|---|
| MAD as a robust scale estimate, and its alternatives | Rousseeuw, P.J. and Croux, C. (1993), "Alternatives to the Median Absolute Deviation", *JASA* 88(424):1273-1283 | verified |
| False discovery rate control | Benjamini, Y. and Hochberg, Y. (1995), *JRSS-B* 57(1):289-300 | verified |

A battery that runs 30 checks across 12 roles is doing hundreds of implicit tests. `tssme`
currently controls this by effect-size gating rather than by FDR correction, which is a
deliberate simplification: a process engineer can act on "2.4 standard deviations" and
cannot act on a corrected p-value. It is recorded as a limitation, not as a solved problem.

## 5. Historian data artifacts

| Claim | Source | Status |
|---|---|---|
| Compression and deadband distort variance, spectra and correlation in derived analyses | Thornhill, N.F., Choudhury, M.A.A.S. and Shah, S.L. (2004), "The impact of compression on data-driven process analyses", *Journal of Process Control* 14(4):389-398 | verified |
| Swinging-door compression, the algorithm behind most historians | Bristol, E.H. (1990), "Swinging door trending: adaptive trend recording?", ISA National Conference proceedings | UNVERIFIED (citation from memory; the algorithm itself is well documented in historian vendor material) |

See `historian-artifacts.md` for the catalog and what each artifact fakes.

## 6. Alarm and detector design

| Claim | Source | Status |
|---|---|---|
| Alarm rate targets and the cost of alarm floods | EEMUA 191, *Alarm Systems: A Guide to Design, Management and Procurement* | verified (document exists and covers this; specific rate figures not quoted here) |
| Alarm rationalisation and lifecycle | ANSI/ISA-18.2, *Management of Alarm Systems for the Process Industries* | verified |

The rule "a detector firing on more than 20 percent of samples is not a detector" is a
`tssme` threshold, not a standard. It is justified by base rates rather than by citation: a
rate-of-change flag thresholded at zero fires on roughly half of all samples by construction,
because roughly half the increments of any mean-reverting series are positive. The 20 percent
figure is a screening threshold, chosen to be far enough above any plausible fault duty cycle
to be unambiguous.

## 7. Liquid pipeline hydraulics

| Claim | Source | Status |
|---|---|---|
| Darcy-Weisbach, Colebrook friction factor, Reynolds number in pipeline units, batching, station hydraulics | Menon, E.S., *Liquid Pipeline Hydraulics*, Marcel Dekker / CRC | verified (work); chapter-approx (the ch. 2, 3, 6, 10 references in the cards) |
| Colebrook friction correlation | Colebrook, C.F. (1939), *Journal of the Institution of Civil Engineers* 11(4):133-156 | verified |
| Turbulent friction gives pressure drop scaling near `Q^1.8` | Consequence of Darcy-Weisbach with a turbulent friction factor; the exponent falls between 1.75 (smooth, Blasius) and 2.0 (fully rough) | verified by derivation |
| Liquid pipeline design and MAOP | ASME B31.4, *Pipeline Transportation Systems for Liquids and Slurries* | verified |
| Computational pipeline monitoring, model-based leak detection | API 1130, *Computational Pipeline Monitoring for Liquids* | verified |
| Uncertainty in pipeline variables and its effect on leak detectability | API 1149, *Pipeline Variable Uncertainties and Their Effects on Leak Detectability* | verified |
| Model-residual methods for leak and blockage detection | Cited in the crude pump station card (`midstream-process-knowledge` skill) as "Liou, J.Fluids Eng 1998"; the likely work is Liou, J.C.P. (1998), "Pipeline Leak Detection by Impulse Response Extraction", *Journal of Fluids Engineering* | **UNVERIFIED** Author, year and journal not yet checked against the document. Confirm before quoting externally. |

**Drag reducing agents.**

| Claim | Source | Status |
|---|---|---|
| Polymeric DRA gives large drag reduction at single-digit to low-tens ppm | Burger, E.D., Chung, H.S. and Munk, W.R., SPE 9419, "Flow Increase in the Trans Alaska Pipeline Through Use of a Polymeric Drag-Reducing Additive", presented 1980, *Journal of Petroleum Technology* 1982 | verified (work); the cards cite it as "SPE 9419 (presented 1980), J.Pet.Tech 1982" |

**Fluid properties.**

| Claim | Source | Status |
|---|---|---|
| Viscosity-temperature relation (Walther equation) | ASTM D341, *Standard Practice for Viscosity-Temperature Charts for Liquid Petroleum Products* | verified |

## 8. Rotating equipment

| Claim | Source | Status |
|---|---|---|
| Centrifugal pump H-Q curve, affinity laws, head conversion `H(ft) = dP(psi) x 2.31 / SG`, wear and clearance loss | Karassik, I.J. et al., *Pump Handbook*, 4th ed., McGraw-Hill (2008) | verified (work); chapter-approx (the ch. 2 and ch. 12 references) |
| NPSH margin, cavitation | ANSI/HI 9.6.1, *Rotodynamic Pumps Guideline for NPSH Margin* | verified |
| Centrifugal pumps for petroleum service | API 610 / ISO 13709 | verified |

## 9. Fault detection and diagnosis

| Claim | Source | Status |
|---|---|---|
| Model-based fault detection, residual generation, and instrument drift as a confounder | Isermann, R. (2006), *Fault-Diagnosis Systems: An Introduction from Fault Detection to Fault Diagnosis*, Springer | verified |
| Condition monitoring and diagnostics of machines, data processing and presentation | ISO 13374 | verified |
| Condition monitoring, general guidelines | ISO 17359 | verified |

The distinction `tssme` draws between a **confounder** (a benign explanation producing the
same signature) and a **differential** (a competing fault) is standard clinical diagnostic
vocabulary applied to process data. Isermann covers the residual-generation half; the
confounder/differential split is a `tssme` modelling choice, justified by the fact that the
two lead to different next steps.

## 10. What is deliberately not cited

Nothing in `tssme` rests on a machine learning result. There is no autoencoder, no isolation
forest, no LSTM. That is a constraint of the runtime (no sklearn, no statsmodels, because the
library has to execute inside a Spotfire CPython data function) and also a choice: a finding
has to carry an interpretation a process engineer can act on, and a reconstruction error does
not. `detector-matrix.md` records which questions the excluded methods would answer better.

## Maintenance rule

If a check fires on a threshold, that threshold appears here or the finding says
`source: UNVERIFIED`. Inventing a plausible-looking citation is worse than admitting the
number came from the data, because a reviewer cannot tell the difference without checking.
