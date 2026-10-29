# Process reference by unit class

**Pending SME review.** Process reference by unit class, written to be authored from. Each section gives what the unit
does, the quantity that actually carries a finding, the roles worth carrying in a card, the
invariants that must hold, and the failure modes with their signatures and confounders.

## How to read the numbers in this file

Every figure here is a **typical design or operating value, not a spec for any specific
asset**. Nothing in this file is a substitute for the unit's own datasheet, the gas processing
agreement, or the product sales contract. When a number moves from here into a card it must
carry a `source`, and if the source is this file then the card should say so and flag it for
confirmation against the asset. The point of the `UNVERIFIED` convention is that a reader can
tell the difference between a checked bound and a plausible one.

Contract-driven values are marked **contract**. They vary by counterparty and are not
guessable.

**Card coverage.** Section 1 has a reviewed card (`crude-pump-station`). Sections 3, 4
(TEG only), 5 and 6 have draft cards generated from this file (`amine-treating`,
`teg-dehydration`, `cryogenic-ngl-recovery`, `ngl-fractionation-column`), pending SME review
and never run against plant data. Section 2 and mol sieve dehydration have no card.

---

## 1. Crude pump station and pipeline segment

The card with the most complete sourcing (`assets/midstream-pack/units/crude-pump-station.yaml`).
Read it as the worked example for everything below.

**Service.** A mainline centrifugal pump station raising pressure, and the pipeline segment
downstream of it consuming that pressure as friction.

**The analysable quantity.** Two of them, and they answer different questions.

- *Head developed at matched flow.* A pump's H-Q curve gives head as a function of flow, so
  head can only be compared at the same flow. Compared across flow, a pump that simply ran
  harder this year looks worn.
- *The measured against predicted pressure drop residual.* Predicted drop comes from
  Darcy-Weisbach with a Colebrook friction factor. The residual is where wax, restriction,
  a DRA change or a model error all show up, which is exactly why the confounders matter.

**Key relationships.**

- `pump_head_ft = (discharge_pressure - suction_pressure) * 2.31 / specific_gravity`
- Turbulent friction gives `dP proportional to Q^n` with `n` between 1.75 (smooth, Blasius)
  and 2.0 (fully rough). An exponent far outside that range means the friction model, the
  assumed diameter, or the flow meter is wrong.
- `Re = 92.24 * Q(bpd) / (D(in) * nu(cSt))`
- Viscosity follows ASTM D341 in temperature, so a seasonal temperature swing drives a
  seasonal friction swing that is not a fault.

**Why the residual band lives on `residual_pct` and not on `residual`.** Across a drop range
of roughly 230 to 955 psi, a fixed psi window is rate-biased: it is loose at high rate and
tight at low rate. The percentage residual has a meaningful band and the raw psi residual does
not. The percentage band is `normative` because it is a model quality target, so a wide miss
means the model is wrong, not that the band needs widening.

**Failure modes.** See the card. The one worth restating is that `transmitter_drift` is a
**differential** of `wax_deposition`, not a confounder: both mean something is wrong, they
just call for different people.

---

## 2. Inlet processing and compression

**Service.** Receive field gas, knock out liquids, raise pressure to treating pressure.
Slug catcher, inlet separator (two or three phase), liquid stabiliser, and one or more
compression stages.

**The analysable quantity.**

- *Separator carryover and carryunder are evidenced downstream, not in the vessel.* A
  separator level transmitter tells you about control, not about separation. Carryover shows
  up as liquid in the amine contactor and as foaming; carryunder shows up as gas in the
  liquid line and as level instability in the stabiliser.
- *Compressor stage compression ratio and discharge temperature at matched ratio.* Discharge
  temperature rises with ratio, so a rising discharge temperature only means anything once
  ratio is held constant. That is a regime, not a correction.

**Roles worth carrying.** `inlet_pressure`, `inlet_temperature`, `separator_level`,
`separator_dp`, `stage_suction_pressure`, `stage_discharge_pressure`,
`stage_discharge_temperature`, `compressor_stages_running`, `recycle_valve_position`,
`liquid_flow`, `gas_flow`.

**Derived.** `compression_ratio = stage_discharge_pressure_abs / stage_suction_pressure_abs`,
`volumetric_efficiency` where rod load and cylinder data exist.

**Failure modes.**

| Mode | Onset | Signature | Confounders | Discriminator |
|---|---|---|---|---|
| Reciprocating valve failure | hours to days | `stage_discharge_temperature` up, `gas_flow` down at fixed speed, interstage pressure shifted toward the failed stage | Ambient temperature rise, cooler fouling, a genuine ratio change | Interstage pressure shift is the tell. Ambient moves both stages, a valve moves one |
| Fouled interstage cooler | weeks | `stage_suction_temperature` up, `compression_ratio` unchanged, `gas_flow` down | Ambient, cooling water temperature, air cooler fan outage | Approach temperature across the cooler separates fouling from ambient |
| Slug carryover to the contactor | instant | `separator_level` sharp_up, then contactor `contactor_dp` sharp_up and `treated_gas_h2s` up within an hour | A genuine feed rate step, an analyser fault | Onset within one sample, and the downstream sequence in the right order |
| Recycle running continuously | days | `recycle_valve_position` up, `gas_flow` flat, `stage_discharge_temperature` up | A genuine low-throughput period | Recycle at high throughput is the finding; at low throughput it is normal turndown |

---

## 3. Amine treating

**Service.** Remove H2S and CO2 from the gas so it meets the sales spec, and so that CO2 does
not freeze in the cryogenic section downstream. Contactor (absorber), rich amine flash tank,
lean/rich exchanger, regenerator (stripper) with reboiler, overhead condenser and reflux,
acid gas to flare, incinerator or sulphur recovery.

**Solvent selection matters to the card.** MEA, DEA, MDEA, formulated MDEA (usually piperazine
promoted), and DGA behave differently. MDEA is kinetically selective for H2S over CO2, so an
MDEA unit's CO2 slip is a design choice and not a fault. A card written for a DEA unit does
not transfer to an MDEA unit without revisiting every band.

**The analysable quantity.**

- *Rich loading*, in moles of acid gas per mole of amine. This is the corrosion driver and the
  capacity indicator. Circulation rate is the MV, not the finding.
- *Treated gas acid gas content*, against the contract spec. **contract**
- *Reboiler duty per mole of acid gas stripped.* Duty alone moves with rate; duty per mole
  stripped is the regenerator's own performance.
- *Contactor dP at matched gas rate*, which is the foaming indicator.

**Typical values, all to be confirmed per asset.**

| Quantity | Typical | Note |
|---|---|---|
| Amine strength | MEA 15 to 20 wt%, DEA 25 to 35 wt%, MDEA 40 to 50 wt% | Design value; drifts with water balance |
| Rich loading limit, carbon steel | roughly 0.35 to 0.45 mol acid gas per mol amine | Commonly cited corrosion limit; verify against the unit's corrosion study |
| Lean loading | low, single digit hundredths for MDEA | Set by stripping duty |
| Lean amine temperature | roughly 10 to 15 F **above** inlet gas temperature | Below the gas temperature, hydrocarbons condense in the contactor and the unit foams. This is one of the most useful single rules in amine monitoring |
| Reboiler duty | order of 1000 to 1200 Btu per gallon of amine circulated | Rule of thumb, strongly solvent and loading dependent |
| Reboiler temperature | solvent specific; thermal degradation is a skin temperature limit, not a bulk one | Verify against the solvent supplier's limit |

**Roles worth carrying.** `inlet_gas_flow`, `inlet_gas_temperature`, `inlet_h2s`, `inlet_co2`,
`treated_gas_h2s`, `treated_gas_co2`, `contactor_dp`, `contactor_pressure`,
`lean_amine_temperature`, `lean_amine_flow` (circulation), `lean_loading` (lab),
`rich_loading` (lab), `amine_strength` (lab), `heat_stable_salts` (lab), `flash_tank_pressure`,
`reboiler_temperature`, `reboiler_duty`, `reflux_flow`, `acid_gas_flow`, `filter_dp`,
`amine_makeup_flow`.

**Invariants.**

- `treated_gas_h2s < inlet_h2s` and `treated_gas_co2 < inlet_co2`. A violation is a swapped
  tag or an analyser fault, not a process event.
- `rich_loading > lean_loading`. Same reasoning.
- Acid gas balance: moles removed from the gas should approximate moles in the acid gas
  stream. This is the identity that verifies the analysers, and it should be checked before
  anything is concluded from either of them.
- `lean_amine_temperature > inlet_gas_temperature` is an operating rule rather than a physical
  truth, so it belongs as a failure mode trigger, not as an invariant.

**Failure modes.**

| Mode | Onset | Signature | Confounders | Differentials | Discriminator |
|---|---|---|---|---|---|
| Foaming | hours | `contactor_dp` sharp_up, `treated_gas_h2s` up, `amine_makeup_flow` up, contactor level erratic | A genuine gas rate step, an instrument fault on dP | Flooding from over-circulation, tray damage | Onset in hours with level instability and amine loss together. A rate step moves dP smoothly and does not cost amine |
| Hydrocarbon condensation in the contactor | days | `lean_amine_temperature` down relative to `inlet_gas_temperature`, then foaming signature | Ambient cooling, a cooler control change | Solids or well chemical carryover causing foaming | The approach between lean amine and inlet gas going negative is the direct evidence, and it precedes the foaming |
| Heat stable salt accumulation | months | `heat_stable_salts` up, `amine_strength` effectively down, `reboiler_duty` per mole stripped up, `treated_gas_h2s` up at fixed circulation | Amine strength drift from water balance, lab sampling error | Solvent degradation from thermal exposure or oxygen ingress | Onset in months and the lab trend. Both need reclaiming, but oxygen ingress needs the source found |
| Lean/rich exchanger fouling | months | Rich amine inlet temperature to the regenerator down, `reboiler_duty` up at fixed acid gas removal | Rate change, ambient | Reboiler tube fouling | Which side of the exchanger the approach degrades on |
| Regenerator under-stripping | days | `lean_loading` up, `treated_gas_h2s` up, `reboiler_temperature` down or `reflux_flow` up | An inlet acid gas load increase, a circulation change | Reboiler fouling | Inlet loading is the confounder to exclude first. Under-stripping at constant inlet load is the finding |
| Amine losses | weeks | `amine_makeup_flow` up, `amine_strength` down, no foaming signature | A genuine inventory change, a drain or sample draw not logged | Foaming carryover, mechanical leak | Losses without a dP signature point to vaporisation or a leak rather than carryover |

---

## 4. Dehydration

**Service.** Remove water so that hydrates do not form and, for cryogenic service, so that ice
does not form in the cold box. Two technologies, and they are not interchangeable.

- **TEG contactor**, for pipeline dew point control. Contactor, flash tank, filters, lean/rich
  exchanger, reboiler, and often a stripping gas or Stahl column. Typical pipeline water spec
  is on the order of 7 lb per MMscf, but it is **contract** specific.
- **Mol sieve** (solid desiccant adsorption), for cryogenic feed. TEG cannot reach cryogenic dryness. Mol sieve beds
  cycle on adsorption, heating, regeneration and cooling, and the target is on the order of
  0.1 ppmv or lower.

**The analysable quantity.**

- TEG: *outlet water dew point against lean glycol purity and reboiler temperature.* Lean
  glycol purity is what does the work, and it is set by reboiler temperature and stripping
  gas. Circulation rate is the MV.
- Mol sieve: *bed breakthrough timing and regeneration gas outlet temperature profile.* A bed
  losing capacity breaks through earlier in the cycle, and the regeneration temperature
  profile shifts. Cycle position must be a regime; comparing a sample early in an adsorption
  cycle to one late in it is meaningless.

**TEG limits worth knowing.** TEG degrades thermally above roughly 400 F, so the reboiler
temperature is bounded above by degradation and below by lean purity. Glycol circulation is
often quoted around 2 to 3 gallons of TEG per pound of water removed. Both figures are rules
of thumb.

**Failure modes.**

| Mode | Onset | Signature | Confounders | Discriminator |
|---|---|---|---|---|
| Low lean glycol purity | days | `reboiler_temperature` down, `outlet_dew_point` up, `lean_glycol_water` up | An inlet water load increase from a wetter or hotter feed, ambient | Inlet water load is a function of inlet temperature and pressure and must be excluded first |
| Glycol losses | weeks | `glycol_makeup_flow` up, contactor dP up if carryover | Inventory change, unlogged drain | Carryover has a dP signature, vaporisation does not |
| Mol sieve capacity loss | months | Breakthrough earlier in the adsorption cycle, regeneration outlet temperature profile shifted | Higher inlet water load, a shortened cycle time change by operations | Normalise breakthrough to water loaded, not to elapsed time |
| Mol sieve bed damage or channelling | instant to days | Breakthrough with an abnormally low bed dP | A valve sequencing fault | Bed dP separates a damaged bed from a saturated one |

---

## 5. Cryogenic NGL recovery

**Service.** Chill treated, dried gas until the C2 and heavier components condense, separate
them from methane, and send residue gas to sales and Y-grade NGL to fractionation.

**Train order and why each step exists.** Inlet separation, compression, amine treating
(because CO2 freezes in the cold section), mol sieve dehydration (because water freezes),
mercury removal (because mercury attacks the brazed aluminium heat exchangers), then the cold
box, turboexpander and demethanizer.

**Process configurations.** ISS, GSP (gas subcooled process) and RSV (recycle split vapour)
are common designs. They differ in how much of the cold feed is subcooled
and refluxed to the demethanizer top, and therefore in achievable ethane recovery. A card must
record which one it describes, because the expected temperature profile differs.

**Ethane recovery and ethane rejection are both normal.** The plant switches between them on
the spread between the ethane frac value and the residue gas value. Recovery mode runs a colder
demethanizer top and a higher recovery; rejection mode deliberately lets ethane go to residue.
**This must be a regime.** Comparing a recovery-mode sample to a rejection-mode baseline
produces a fault finding on every switch, and the switch is a commercial decision.

**The analysable quantity.**

- *Cold box approach temperatures.* Brazed aluminium exchangers run tight approaches, on the
  order of a few degrees F. The approach is the exchanger's own performance and it degrades
  before anything else shows.
- *Cold box dP.* This is the freeze indicator. A rising dP with a degrading approach is ice or
  CO2 solids forming.
- *Turboexpander isentropic efficiency*, typically around 80 to 85 percent when healthy.
- *Demethanizer bottoms methane content*, which is the Y-grade quality spec. **contract**
- *Residue gas ethane content*, which is the recovery measure and should be read against the
  mode.

**Roles worth carrying.** `inlet_gas_flow`, `inlet_co2`, `inlet_water`, `coldbox_dp`,
`coldbox_hot_inlet_temperature`, `coldbox_cold_outlet_temperature`, `expander_inlet_pressure`,
`expander_outlet_pressure`, `expander_inlet_temperature`, `expander_outlet_temperature`,
`expander_speed`, `booster_discharge_pressure`, `demethanizer_pressure`,
`demethanizer_top_temperature`, `demethanizer_bottoms_temperature`, `reflux_flow`,
`residue_gas_flow`, `residue_gas_c2_frac`, `ngl_flow`, `ngl_c1_frac`, `recovery_mode` (status).

**Derived.** `expander_ratio`, `expander_isentropic_efficiency`, `coldbox_approach`,
`c2_recovery_pct`.

**Invariants.**

- `expander_outlet_temperature < expander_inlet_temperature` and
  `expander_outlet_pressure < expander_inlet_pressure`. Violations are tag or sign errors.
- Component balance: C2 into the plant equals C2 in residue plus C2 in NGL, within metering
  uncertainty. This is the identity that validates the chromatographs, and recovery percentage
  means nothing until it holds.
- `c2_recovery_pct` monotonic in demethanizer top coldness **requires** `recovery_mode`,
  because in rejection mode the relationship is deliberately broken.

**Failure modes.**

| Mode | Onset | Signature | Confounders | Differentials | Discriminator |
|---|---|---|---|---|---|
| Cold box freeze (CO2 or water) | hours to days | `coldbox_dp` up, `coldbox_approach` up, `c2_recovery_pct` down | A rate increase raising dP legitimately, a mode switch | Cold box fouling from heavies or lube oil, mechanical maldistribution | dP normalised to rate is the test. A freeze also traces back to an amine or mol sieve excursion a few hours earlier, so look upstream before the cold box |
| Amine CO2 slip feeding the cold box | days | `inlet_co2` to the cold section up, then the freeze signature | Analyser drift, an inlet composition change | Mol sieve breakthrough (water rather than CO2) | Which upstream unit's own signature is also present. Both end at the cold box |
| Mol sieve breakthrough | hours | `inlet_water` up at the cold section, then freeze signature, correlated with cycle position | A cycle time change | CO2 slip | Correlation with adsorption cycle position |
| Turboexpander performance loss | weeks | `expander_isentropic_efficiency` down at matched ratio, `expander_outlet_temperature` up, `c2_recovery_pct` down | Rate or ratio change, a mode switch, ambient | Cold box fouling | Matched-ratio comparison. Efficiency down at matched ratio is the expander; approach degraded with efficiency intact is the exchanger |
| Demethanizer flooding | hours | Column dP up, `ngl_c1_frac` up **and** `residue_gas_c2_frac` up together | A genuine rate increase | Reboiler or side-heater problem | Both product streams degrading at once is the flooding signature. One stream alone is a duty problem |

---

## 6. Y-grade fractionation

**Service.** Split Y-grade (raw make NGL) into purity products. The train runs in order of
volatility: deethanizer, depropanizer, debutanizer, and where isobutane is a separate product,
a deisobutanizer.

| Column | Overhead | Bottoms | Notes |
|---|---|---|---|
| Deethanizer | Ethane or an E/P mix | C3 and heavier | Runs at high pressure, roughly 400 to 450 psig, so the overhead condenser needs propane refrigerant. The coldest and most refrigeration-sensitive column in the train |
| Depropanizer | Propane | C4 and heavier | Product is usually HD-5 propane. **contract** |
| Debutanizer | Mixed butanes | Natural gasoline (C5 plus) | Bottoms quality is set by RVP. **contract** |
| Deisobutanizer | Isobutane | Normal butane | Relative volatility near 1.25, so it needs a high tray count and a high reflux ratio. It is the most energy intensive split in the train and the most sensitive to tray damage |

**Product specs are contractual.** Propane HD-5 is commonly stated as a minimum 90 liquid
volume percent propane, a maximum 5 liquid volume percent propylene, and a maximum vapour
pressure of 208 psig at 100 F, per GPA 2140 and ASTM D1835. **Confirm against the current
standard and the sales contract before putting any of it in a card.** Ethane and natural
gasoline specs vary more and are purely contract driven.

**The analysable quantity.**

- *Separation achieved per unit of reflux and reboil.* Not the product purity alone, which can
  always be bought with more energy, and not the energy alone, which moves with rate. The
  ratio is the column's performance.
- *Pressure compensated tray temperature.* A tray temperature is a composition proxy only at
  constant pressure. Use PCT, or carry `column_pressure` as a regime. Reading a raw tray
  temperature as composition across a pressure change invents a fractionation problem.
- *Column dP at matched vapour rate*, which is the flooding and fouling indicator.

**Roles worth carrying.** `feed_flow`, `feed_temperature`, `feed_composition_*`,
`column_pressure`, `column_dp`, `overhead_temperature`, `bottoms_temperature`,
`tray_NN_temperature` for the sensitive tray, `reflux_flow`, `distillate_flow`,
`bottoms_flow`, `reboiler_duty`, `condenser_duty`, `overhead_impurity` (the heavy key in the
distillate), `bottoms_impurity` (the light key in the bottoms), `refrigerant_temperature` for
the deethanizer.

**Derived.** `reflux_ratio = reflux_flow / distillate_flow`,
`boilup_ratio = reboiler_vapour / bottoms_flow`, `separation_factor` from the two impurities,
`pct_tray_NN` (pressure compensated temperature), `condenser_approach`, `reboiler_approach`.

**Invariants.**

- Overall mass balance: `feed_flow = distillate_flow + bottoms_flow`, within metering
  uncertainty. Check this before reading anything else. A column that does not balance has a
  meter problem, and every ratio derived from those flows inherits it.
- Component balance on the light key.
- `overhead_temperature < bottoms_temperature`.
- Separation improves with reflux ratio at constant feed. This is **monotonic and conditional**:
  it holds at constant feed composition and below the flood point, so it must declare
  `requires_roles` against feed composition, and it inverts above flooding. An unconditioned
  version of this invariant will report a flooding column as a tag error.

**Failure modes.**

| Mode | Onset | Signature | Confounders | Differentials | Discriminator |
|---|---|---|---|---|---|
| Flooding | hours | `column_dp` sharp_up faster than proportional to boilup, temperature profile collapsing (trays converging), `overhead_impurity` up **and** `bottoms_impurity` up together | A genuine rate increase, a feed composition change | Foaming, tray damage, a plugged downcomer | Both impurities rising together is the flooding tell. A duty problem moves one. dP rising faster than proportionally separates flooding from rate |
| Weeping or dumping at low rate | hours | `column_dp` low for the rate, `bottoms_impurity` up, `overhead_impurity` roughly unchanged | A genuine turndown period | Tray damage | Turndown is normal; the finding is weeping at a rate the column should handle |
| Tray damage | instant, then persistent | Step change in `column_dp` at fixed rate, separation efficiency down permanently, no recovery after a rate reduction | A pressure transmitter recalibration, a rate step | Fouling | A step that does not recover after the rate returns. Fouling ramps, damage steps |
| Fouling or coking | months | `column_dp` up at matched rate, `reboiler_approach` up, `reboiler_duty` up for the same separation | Rate creep, ambient, a feed composition shift to heavies | Tray damage | Onset in months, and gradual |
| Reboiler duty limitation | weeks | `bottoms_impurity` up, `reboiler_duty` at maximum, `reboiler_approach` up | A feed rate or composition increase | Fouling, a steam or hot oil supply problem | Whether the utility side or the process side approach degraded |
| Deethanizer condenser refrigeration loss | hours | `overhead_temperature` up, `refrigerant_temperature` up, `overhead_impurity` (C3 in ethane) up, reflux down | Ambient, a genuine rate increase | Condenser fouling | Refrigerant side temperature rising with it points to the refrigeration system, not the exchanger |
| Feed composition shift | days | Temperature profile shifted with `column_dp` and duties unchanged, both products shifted in the same direction | An analyser fault | Any column fault | This is a **confounder** for almost every mode above, and it is the first thing to exclude. A profile shift with no dP or duty change is composition, not equipment |

---

## 7. Signature patterns that repeat across unit classes

Worth knowing because they let one card's failure mode be written by analogy from another.

- **Both product streams degrading at once means a hydraulic problem** (flooding, foaming,
  carryover). One stream degrading means a duty or separation driving force problem. This holds
  for every column, and for the demethanizer.

- **A step that does not recover when the rate returns is mechanical damage.** A ramp is
  fouling or wear. A step that recovers is an operating change. Onset is the primary
  discriminator, which is why `onset` is a required field on every failure mode.

- **An approach temperature degrading with efficiency intact is the exchanger.** Efficiency
  degrading at matched conditions with the approach intact is the machine. Both degrading is
  usually upstream.

- **An upstream unit's excursion arrives downstream with a lag and in order.** Amine CO2 slip,
  then cold box dP. Separator carryover, then contactor foaming. When several units show a
  signature in the same window, the ordering identifies the source, and reporting all of them
  as separate faults is the standard way to lose it.

- **The MV moves before the CV does.** A controller absorbs degradation until it saturates.
  The finding is in the controller's effort, and by the time the controlled variable moves the
  unit is already out of margin.

---

## 8. What this file does not cover

Honest scope statement, because the alternative is a reader assuming coverage that is not
there.

- **No SRU, no tail gas treating, no fired heater detail.**
- **No compressor surge analysis.** That needs a compressor map and fast data, and neither is
  available in a daily export.
- **No leak detection.** Model-based CPM (API 1130) needs station-to-station mass balance and
  a transient hydraulic model. A single unit card cannot do it, and claiming otherwise from a
  residual trend would be wrong.
- **No relief, flare or safety system analysis.** Out of scope by design; that work has its own
  standards and its own reviewers.
- **No composition modelling.** There is no equation of state here. Where a card needs a
  property, it uses a correlation with a citation (ASTM D341 for viscosity, for example) or it
  carries the lab value and declares it `lab`.
- **Draft cards are not reviewed cards.** The amine, TEG, NGL recovery and fractionation cards
  are drafts generated from this file. Inlet processing, compression and mol sieve
  dehydration have no card. A report must not imply coverage that does not exist.
