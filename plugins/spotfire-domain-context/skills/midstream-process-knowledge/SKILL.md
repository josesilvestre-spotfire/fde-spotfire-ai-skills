---
name: midstream-process-knowledge
description: Provides process engineering knowledge for midstream oil and gas units as YAML unit cards plus a process reference, covering crude pump stations (validated card), amine treating, TEG dehydration, cryogenic NGL recovery and Y-grade fractionation (draft cards pending SME review). Each card states the unit's measurement roles, the quantity that carries a finding, invariants, operating regimes, confounders and failure modes with multi-tag signatures. Use when working out what a midstream unit's sensors should be doing, when checking whether an app's or analysis's conclusion about such a unit is physically plausible, or when writing or reviewing a unit card. Cards are a knowledge pack for the analyzing-process-time-series skill, which validates them and turns them into checks.
metadata:
  maturity: "Pump station card proven on one machine; four draft cards new, not yet tested"
---

# Midstream process knowledge

**Pending SME review:** the engineering content (cards, signatures, typical values) has not yet been reviewed by an independent process SME; four of the five cards are drafts.

This skill holds class knowledge about midstream units in two forms:

- **Unit cards** (`assets/midstream-pack/units/*.yaml`): validated data that a time series
  engine can execute. Each card names the roles a unit is measured by, the derived quantity
  that carries a finding, invariants that must hold, the regimes to segment by, confounders
  (benign explanations) and failure modes with multi-tag signatures, onset rates and field
  checks.
- **A process reference** ([references/unit-reference.md](references/unit-reference.md)):
  per unit class, what the unit does, what to measure, how it fails, and typical values to
  author from, every one flagged as typical or contractual.

A card carries no operating bands for any particular asset and no tag names. Those are
deployment facts and belong in a profile (see the `analyzing-process-time-series` skill).

## What exists

| Card | Unit class | Status |
|---|---|---|
| `crude-pump-station` | `pump_station` | Sourced card with citations; ships a pack check (`sme_head_deficit_at_matched_flow`). Validates. Pending SME review |
| `amine-treating` | `amine_treating` | Draft from the process reference. Validates. Failure modes `UNVERIFIED`. Never run on plant data |
| `teg-dehydration` | `dehydration_teg` | Draft. Validates. Two failure modes only. Never run on plant data |
| `cryogenic-ngl-recovery` | `ngl_recovery` | Draft. Validates. Mode (recovery or rejection) is a required regime. Never run on plant data |
| `ngl-fractionation-column` | `distillation_column` | Draft, generic across deethanizer to deisobutanizer. Validates. Never run on plant data |

Inlet separation, compression and mol sieve dehydration have reference text but no
card. Do not imply coverage that does not exist.

## Using a card without the engine

Read the card for the unit in question and answer from it:

1. **Which quantity carries the finding?** It is usually a derived quantity (a residual, an
   approach, a loading, a separation factor), not a raw tag.
2. **Which regime must the comparison stay inside?** Rate, operating mode, pumps running,
   column pressure.
3. **Which failure modes match the observed directions and onset?** A signature needs two
   or more roles moving the declared way at the declared speed.
4. **Which confounders must be excluded first, and which roles evidence them?** If the
   evidencing role is missing or constant, the confounder is untestable, not ruled out.
5. **What would a person check in the field?** `verify_in_field` on each failure mode.

When an app or analysis claims a fault, check it against the card: a claim built on one
tag, across a regime change, or without its confounders excluded is a hypothesis, not a
diagnosis.

## Using the cards with the engine

The `analyzing-process-time-series` skill discovers this pack automatically when both skills
are installed side by side; otherwise set `TSSME_PACK_PATH` to the full path of
`assets/midstream-pack`. Then, from that skill's `scripts/` folder:

```bash
python -m tssme cards --validate --pack midstream-process
python -m tssme analyse --data export.csv --unit amine-treating --pack midstream-process \
       --tagmap tagmap.yaml --out report.md
```

Validation requires that skill: the schema and the validator live there.
[references/authoring-unit-cards.md](references/authoring-unit-cards.md) lists every card
field, so you can write a card without it.

## Process rules that generalise across midstream units

- **A controlled variable is not evidence of health.** A CV on setpoint with low variance
  shows the controller works. Degradation shows first in the MV, the controller's effort.
- **A tray temperature is a composition proxy only at constant pressure.** Use a
  pressure-compensated temperature or carry column pressure as a regime.
- **Approach temperature beats absolute temperature for any exchanger.** The absolute value
  moves with ambient, feed and rate; the approach is the exchanger's own performance.
- **Normalise a pressure drop by rate before banding it.** Friction and tray dP scale with
  roughly the square of flow, so a fixed dP band reports the throughput schedule as a fault.
- **Loading, not circulation.** For amine and glycol the analysable quantity is acid gas or
  water loading per unit of solvent. Circulation is the MV.
- **Composition specs are contractual, so their bands are `normative`.** Model residuals are
  normative too. Observed envelopes are `descriptive`.
- **Seasonal is not a fault.** Ground and ambient temperature and demand move on an annual
  cycle. A slow trend over less than a year is confounded with season until shown otherwise.
- **A lab role that updates every sample is modelled, not assayed**, so it cannot
  independently corroborate anything.
- **Both product streams degrading at once is a hydraulic problem** (flooding, foaming,
  carryover). One stream degrading is a duty or driving-force problem.
- **A step that does not recover when rate returns is mechanical damage.** A ramp is fouling
  or wear. A step that recovers is an operating change.
- **An upstream excursion arrives downstream with a lag and in order** (amine CO2 slip, then
  cold box dP). The ordering identifies the source; reporting each unit separately loses it.

## Where each unit's finding lives

| Unit class | The quantity that carries the finding |
|---|---|
| `pump_station` | Head at matched flow, and the measured against predicted pressure drop residual |
| `pipeline_segment` | Rate-normalised friction residual against a Colebrook model |
| `compressor` | Stage compression ratio, and discharge temperature at matched ratio |
| `inlet_separator` | Carryover and carryunder, evidenced downstream rather than in the vessel |
| `amine_treating` | Rich loading, treated gas acid gas content, contactor dP at matched rate, reboiler duty per unit circulated |
| `dehydration_teg` | Outlet water dew point against lean glycol purity and reboiler temperature |
| `ngl_recovery` | Cold box approach and dP, expander outlet temperature at matched ratio, ethane recovery read against mode |
| `heat_exchanger` | Approach temperature and UA at matched duty |
| `distillation_column` | Separation achieved for the reflux and reboil spent, with pressure-compensated tray temperatures |
| `storage_tank` | Mass balance closure, not level |

## Out of scope

No sulphur recovery, tail gas or fired heater detail; no compressor surge analysis; no leak
detection (model-based CPM under API 1130 needs station-to-station mass balance and a
transient model); no relief, flare or safety system analysis; no equation of state.

## References

- [references/unit-reference.md](references/unit-reference.md): process reference by unit
  class, with typical values, failure mode tables and cross-unit signature patterns.
- [references/authoring-unit-cards.md](references/authoring-unit-cards.md): card fields,
  order of work, hard rules, canonical role vocabulary, validation and the workflow for a new
  card.
- `assets/midstream-pack/`: the pack (`pack.yaml`, `schema/extensions.yaml`, `units/`,
  `checks/rotating.py`).
