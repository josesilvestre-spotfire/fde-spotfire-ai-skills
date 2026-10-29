# Authoring packs, profiles, bundles and checks

How to add knowledge, deployments and checks to `tssme` without editing the engine. Run every
command from the skill's `scripts/` folder, or put that folder on `PYTHONPATH`.

## A pack (class knowledge)

A pack is a directory with `pack.yaml`. It is discovered, never registered. The engine
scans, in order:

1. `TSSME_PACK_PATH` (os.pathsep separated; each entry is a pack or a folder of packs)
2. `scripts/packs/` (vendored packs in a deployed copy of the engine)
3. the `assets/` folder of every skill installed next to this one (the
   `midstream-process-knowledge` skill ships its pack there)
4. `assets/examples/` (the synthetic example pack)

```yaml
pack_id: <id>                       # unique; two packs claiming one id is an error
name: <display name>
version: 1.0.0
engine: ">=1.1,<2.0"
schema_extensions: schema/extensions.yaml   # optional: new unit_class/persona/quantity values
units_dir: units                            # default
check_modules: [checks/<module>.py]         # optional: domain checks, registered via @check
```

A check that encodes physics belongs in a pack, not in `tssme/checks/`. The test: would the
check mean anything to a different industry? If not, it is domain knowledge written in
Python.

`schema/extensions.yaml` may extend only `unit_class`, `persona` and `quantity`:

```yaml
extends: "1.0"
enums:
  unit_class: [widget_train]
  persona: [widget_engineer]
  quantity: [head, viscosity]
hard_rules:
  - "Domain rule shown alongside the core rules."
```

## A unit card

A card is a validated YAML document under the pack's `units/` folder. The full field list is
in `scripts/tssme/schema/core.yaml`. Order of work:

1. **Roles.** What is measured, its `kind` (`sensor`, `lab`, `calculated`, `status`,
   `manual`), `quantity`, `units`, `control_role` and `source`. `kind` drives every data
   quality expectation downstream; a `lab` role needs a realistic `update_interval`.
2. **Derived quantities.** The analysable quantity is rarely a raw tag: an approach
   temperature, a residual, a loading, a normalised drop.
3. **Invariants.** Identities first, because they verify the source system. An invariant that
   holds only under a condition declares `requires_roles`.
4. **Regimes.** How to segment before comparing (`bin`, `discrete` or `changepoint`).
5. **Confounders.** Benign explanations, each with the roles that evidence it and a `test`
   (`regime_shift`, `correlates_with`, `step_change` or `zero_order_hold`).
6. **Failure modes last.** Each has a signature over two or more roles, an `onset`,
   `confounders`, optional `differentials`, `discriminators`, `verify_in_field` and a
   `source`.

Validate after every edit:

```bash
python -m tssme cards --validate             # every card in every discovered pack
python -m tssme cards --validate --pack <id> # one pack
```

A class card carries no descriptive operating bands. An envelope measured on one asset is a
profile fact and goes in a calibration overlay.

## A profile (deployment facts)

A profile is a directory with `profile.yaml`. Everything it references resolves relative to
that directory. Profiles are the only layer allowed to contain site facts. The engine scans
`TSSME_PROFILE_PATH`, `scripts/profiles/` and `assets/examples/`.

```yaml
profile_id: <id>
unit: <unit card id>
pack: <pack id>                 # optional, disambiguates a unit id two packs share
tagmap: tagmap.yaml
calibration: calibration.yaml   # optional band overlay
asset: <asset id>               # only for an export that holds several assets
data: data.csv                  # optional default input
checks:
  enabled: [...]                # optional override of the card's list
```

**Tag map.** Maps role ids to column names. `match` is `exact` (default), `suffix`,
`prefix` or `regex`, per map or per role. A multi-asset export declares `asset_pattern` with
a named `(?P<asset>...)` group and uses `{asset}` in templates. Columns matching
`detector_pattern` (default `^Events?\s*-\s*`) are audited as existing event flags.

```yaml
time_column: Timestamp
match: exact
roles:
  inlet_pressure: PI-1001.PV
  flow: {template: "FI-1004.PV", match: suffix}
```

**Calibration overlay.** May set only `normal`, `band_type`, `limits`, `source`,
`update_interval` and `required` on roles and derived quantities that already exist on the
card. It must carry a top-level `source` naming the asset and the period the numbers were
measured over; the loader refuses an overlay without one. Calibrate from the unclamped
interior that `dq_rail_saturation` reports, never from the observed min and max.

## A bundle (a named deliverable)

A bundle names a selection across engine, packs and profiles, plus a brief that states what
the selection analyses and what it refuses. The engine scans `TSSME_BUNDLE_PATH`,
`scripts/bundles/` and `assets/examples/bundles/`.

```yaml
bundle_id: <id>
name: <the name a user says out loud>
version: 1.0.0
persona: <persona value some pack contributes>
engine: {id: tssme, version: ">=1.1,<2.0"}
packs:
  - {id: <pack-id>, version: ">=1.0,<2.0"}    # units omitted: every unit this persona owns
  - {id: <pack-id>, units: [<unit-id>]}       # or an explicit subset
profiles: [<profile-id>]
brief:
  scope: what this selection analyses
  leads_with: the question it answers first
  audience: who reads the output and what they need in it
  refuses: [...]                              # required
outputs: {agent: null, spotfire: null}
```

Everything is referenced by id, never by path, because the same manifest has to resolve
against local search paths during development and inside a vendored copy in deployment.
`brief.refuses` is required: a deliverable that does not state its limits will be used past
them. `python -m tssme bundles --show <id>` reports every missing pack, unit or profile as a
listed problem. A packager that turns a bundle into a deployable artifact is not built.

## Adding a check

```python
from tssme.checks import check
from tssme.findings import Finding
from tssme.prep import Context

@check("stat_my_check", "statistical", requires=("flow",),
       description="One line, shown in `python -m tssme checks`")
def stat_my_check(ctx: Context) -> list[Finding]:
    mask = ctx.X["flow"] > 0
    return [Finding(
        check_id="stat_my_check", unit_id=ctx.unit_id, severity="medium",
        roles=["flow"], window=ctx.window_of(mask),
        summary="One sentence stating the defect.",
        statistic={"n": int(mask.sum())},          # the numbers behind the claim
        interpretation="What it means in the plant, not what the code did.",
        next_step="What a person should physically check.",
        source="Literature backing the rule that fired.",
        kind="defect",                              # defect | candidate | verified | not_evaluated
    )]
```

`summary` states the defect. `interpretation` is the SME reading. `next_step` is a physical
action. `source` is a citation. A finding without `interpretation` and `next_step` is a
number, not a finding. Categories run in the fixed order `data_quality`, `physical`,
`relational`, `statistical`, `sme`. A check whose `requires` roles are missing is skipped and
reported as skipped.

## Workflow: a new unit, end to end

Use this when you extend the engine to a unit it has never seen.

1. Write the card in a pack and run `python -m tssme cards --validate` until it passes.
2. Write the tag map and, if you measured any band, the calibration overlay in a profile
   directory.
3. Confirm the asset dimension: `python -m tssme assets --data <export> --tagmap <map>`.
4. Run `python -m tssme analyse --profile <profile> --out report.md`.
5. Run `python tests/test_tssme.py`; every existing regression test must still pass.
6. Read the report critically and fix what it exposes:
   - Does any check claim health while reporting a large number? That is a swallowed
     finding.
   - Does one physical event appear as several findings on correlated tags?
   - Is any descriptive band missed on more than 20 percent of samples? The card or overlay
     is wrong. Recalibrate, excluding clamped samples.
   - Does any detector fire on more than 20 percent of samples?
   - Is anything filed under "Verified as healthy" that was never evaluated?
   - Any hard limit firing usually means the tag map is wrong, not the plant.
   - Any identity invariant that fails means the source system or the column alignment is
     wrong. Resolve it before reading anything else.
7. Add a regression test for every defect you found. It must fail before the fix and pass
   after.
8. List what is `UNVERIFIED` and what is out of scope.

Where you cannot source a bound, write `UNVERIFIED` rather than guessing. Where the data
contradicts the card (a lab tag that updates every sample, a constant tag that should vary),
report the contradiction rather than adjusting the card to hide it.
