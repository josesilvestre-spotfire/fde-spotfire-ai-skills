# Authoring and validating a unit card

A unit card is a YAML document that states what a unit is, what its measurements mean, how
it fails, and what confounds each failure. It is data, not prose: it is validated, reviewed
like code, and compiled into checks by the `tssme` engine in the `analyzing-process-time-series`
skill.

## Validation needs the engine

The validator, the structural schema (`tssme/schema/core.yaml`) and the checks live in the
`analyzing-process-time-series` skill. This skill ships the vocabulary
(`assets/midstream-pack/schema/extensions.yaml`) and the cards. To validate:

```bash
# from the scripts/ folder of the analyzing-process-time-series skill
python -m tssme packs                                  # the midstream-process pack is listed
python -m tssme cards --validate --pack midstream-process
```

When both skills are installed from the same plugin, the engine finds this pack on its own
(it scans the `assets/` folder of skills installed next to it). Otherwise point it at the
pack: set `TSSME_PACK_PATH` to the full path of `assets/midstream-pack`.

Without the engine you can still read and write cards; the field list below is the contract
the validator enforces.

## Card fields

Top level: `card_version` ("1.0"), `unit_id` (kebab-case, equals the file name), `unit_class`
and `persona` (from this pack's vocabulary), `service`, `roles` are required. `description`,
`topology`, `derived`, `invariants`, `failure_modes`, `confounders`, `regimes`, `checks` and
`notes` are optional. No other keys.

| Section | Field | Required | Notes |
|---|---|---|---|
| roles | `id` | yes | Canonical role name, never a historian tag |
| | `description`, `units`, `source` | yes | `source` is a citation, a reason, or `UNVERIFIED` |
| | `kind` | yes | `sensor`, `lab`, `calculated`, `status`, `manual` |
| | `quantity` | yes | Engine base (pressure, flow, temperature, ...) or this pack's (head, viscosity, loading, ...) |
| | `normal` + `band_type` | no | `[lo, hi]`; `band_type` is required when `normal` is given: `descriptive` or `normative` |
| | `limits` | no | `{lo, hi}` physically impossible outside |
| | `control_role` | no | `CV`, `MV`, `DV`, `IND` (default) |
| | `update_interval`, `required` | no | Lab cadence; `required: false` for optional roles |
| derived | `id`, `expr`, `units`, `source` | yes | `expr` is a Python expression over role ids |
| invariants | `id`, `kind`, `expr`, `source` | yes | `kind`: `identity`, `inequality`, `balance`, `power_law`, `monotonic`, `range` |
| | `tol`, `tol_abs`, `severity`, `requires_roles` | no | `requires_roles` turns a conditional invariant into "not evaluated" when the condition role is absent |
| confounders | `id`, `description`, `roles`, `test`, `source` | yes | `test`: `regime_shift`, `correlates_with`, `step_change`, `zero_order_hold` |
| failure_modes | `id`, `name`, `severity`, `onset`, `signature`, `confounders`, `source` | yes | `signature` maps two or more roles to `up`, `down`, `sharp_up`, `sharp_down`, `erratic`, `flat`, `unchanged`; `onset` is `instant`, `hours`, `days`, `weeks`, `months` |
| | `differentials`, `discriminators`, `verify_in_field` | no | `differentials` name other failure modes on the same card |
| regimes | `id`, `by`, `method` | yes | `method`: `bin` (with `params.width`), `discrete`, `changepoint` |

Expression forms the checks parse: `a == b` (identity, balance), any boolean expression
(inequality), `y ~ x ** n` with `expected` and `tol` (power_law), `y increasing in x` or
`y decreasing in x` (monotonic), `mean(x) in [lo, hi]` (range). An invariant the checks
cannot evaluate is reported as not evaluated.

## Order of work

1. **Roles first.** Get `kind` right on every role; it drives every data quality expectation
   downstream. A `lab` role is zero-order-held in any export.
2. **Derived quantities.** The analysable quantity is rarely a raw tag: an approach
   temperature, a residual, a loading, a normalised drop, a reflux ratio.
3. **Invariants.** Identities and balances first, because they verify the source system
   before anything is built on it.
4. **Regimes.** Anything that switches the expected behaviour is a regime, not a fault: rate,
   ethane recovery or rejection, pumps running, adsorption cycle position, column pressure.
   A rate regime binned on rate as a percentage of design (a `manual` design-rate role)
   works for any unit size.
5. **Confounders**, each with the role that evidences it.
6. **Failure modes last**, because they reference confounders by id and a signature means
   something only once the roles exist.

## Hard rules

The validator enforces most of these; each exists because breaking it produced a wrong
answer.

1. **Every numeric bound carries a `source`**: a citation, or the literal `UNVERIFIED` so it
   surfaces in the report. Never invent a range to make a check pass, and never quote a spec
   from memory as though it were confirmed.
2. **Role ids are canonical and plant-agnostic.** Tag names and asset ids live in the
   deployment profile's tag map.
3. **A class card carries no descriptive operating bands.** An envelope belongs to one asset
   and goes in a calibration overlay with its own `source` naming the asset and the period.
   What stays on the card: physics, identities, failure modes, confounders, regimes, hard
   `limits` and `normative` bands (specs and model quality targets).
4. **Every `normal` band declares `band_type`.** A wide miss on a `descriptive` band means
   the band is wrong; a wide miss on a `normative` band is the finding and the band is never
   widened.
5. **Never calibrate a band from a transmitter rail.** Use the unclamped interior that
   `dq_rail_saturation` reports.
6. **Put the band on the derived quantity where the raw one is rate-biased.** A fixed dP
   window across a wide rate range reports the throughput schedule as a fault.
7. **A signature with one role is a threshold alarm.** Two or more roles.
8. **Every failure mode lists `confounders`.** A mode with no confounders has not been thought
   about.
9. **Confounders and differentials are different fields.** A confounder is benign (nothing
   is wrong); a differential is a competing fault (something else is wrong). The validator
   flags a failure mode id listed under `confounders`.
10. **An invariant that holds only under a condition declares `requires_roles`.** Note the
    limit: the gate checks that the condition role is present, it does not restrict the
    evaluation to rows where the condition holds. An invariant that needs row filtering (for
    example, valid only in ethane recovery mode) cannot be carried yet.
11. **`onset` is the primary discriminator.** A step that does not recover is mechanical
    damage, a ramp is fouling or wear, a step that recovers is an operating change.
12. **Product specs are contractual.** Mark them contract-driven and `UNVERIFIED`; they come
    from the deployment profile.

## Canonical role vocabulary

Reuse these ids across cards so a check written for one unit class transfers. Prefix by
position where a unit has several of the same measurement.

```
pressure        suction_pressure, discharge_pressure, inlet_pressure, outlet_pressure,
                column_pressure, column_dp, contactor_dp, coldbox_dp, filter_dp
temperature     inlet_gas_temperature, overhead_temperature, bottoms_temperature,
                sensitive_tray_temperature, reboiler_temperature, lean_amine_temperature
flow            feed_flow, inlet_gas_flow, reflux_flow, distillate_flow, bottoms_flow,
                lean_amine_flow, residue_gas_flow, design_gas_flow, design_feed_flow
composition     inlet_c2_frac, residue_gas_c2_frac, ngl_c1_frac, treated_gas_h2s,
                treated_gas_co2, lean_loading, rich_loading, overhead_impurity,
                bottoms_impurity
equipment       pump_speed, pumps_running, expander_speed, recovery_mode
derived         pump_head, residual, residual_pct, reflux_ratio, reynolds, feed_rate_pct,
                coldbox_approach, lean_amine_approach, separation_factor
```

`pumps_running` and `pump_speed` exist so an H-Q invariant can declare `requires_roles`
against them. A mainline station that brings a second pump online shows head rising with
flow, and an unconditioned monotonicity invariant reports that as a fault.

## Workflow: a new card from a historian export

Inputs: the unit and its class, the persona, the configuration that changes the expected
behaviour (GSP or RSV, MDEA or DEA, recovery or rejection), the tag list, the sample cadence,
and an explicit out-of-scope statement.

1. Write `assets/midstream-pack/units/<unit-id>.yaml` and validate it until it passes.
2. In a deployment profile directory (not in this skill), write `tagmap.yaml`, and
   `calibration.yaml` only if you measured bands, then `profile.yaml`.
3. From the engine's `scripts/` folder:

   ```bash
   python -m tssme assets  --data <export> --tagmap <profile>/tagmap.yaml
   python -m tssme analyse --profile <profile> --out report.md
   ```

4. Let the report correct the card, in this order:
   1. A hard limit firing usually means the tag map is wrong, not the plant.
   2. A descriptive band missed on more than 20 percent of samples is a wrong band.
      Recalibrate in the overlay, excluding rails, and say so in its `source`.
   3. An identity or balance that does not hold means the source system or the column
      alignment is wrong. Resolve it before reading anything else.
   4. A role reported as flatlined, railed, held or duplicated changes what it can evidence.
      A constant confounder cannot exclude anything; say so in the failure mode.
   5. A `lab` role updating every sample is mis-declared. Fix `kind` or record the
      contradiction in `notes`.
5. Deliver the card, the profile files, the report, a `notes` block with every open data
   question and contradiction, and a list of what is `UNVERIFIED` and out of scope.

Where the data contradicts process expectation (a lab tag updating every sample, a dosing
tag that never changes, a monotonic relationship with the wrong sign), report the
contradiction rather than adjusting the card to hide it.
