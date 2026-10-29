---
title: Known gaps in the alpha
---

# Known gaps in the alpha

What `0.1.0-alpha.1` has not proven yet, by plugin. Testers: report anything you find against the
skill named in the row.

## Library-wide

| Gap | Detail |
|---|---|
| Clean-profile test | No skill has run from a fresh Claude Code profile without the original local skills and notes. |
| Second machine | Everything marked "Proven" was proven on one Windows 11 machine with Spotfire Analyst 15.0. |
| Evals | The eval cases exist for every plugin; `claude plugin eval` has not been run on them yet. |
| `npx skills` | Not tested against this private repo. |
| API index generator | `dump_api.ps1` was edited for public members only and has not been re-run. Two adaptations exist (in `spotfire-reference` and `building-spotfire-dxps`); they are to be merged into one. |

## spotfire-ingest

| Skill | Gap |
|---|---|
| `ingesting-excel-workbooks` | Run on synthetic fixtures only; 2-3 real engineering workbooks still to run. The Excel COM paths (snapshots, recalculating cases) and the `formulas` engine are not tested. `.xls`, `.xlsb` and password-protected files are not read. Unit checks need units in labels; `OFFSET` can leave the dependency graph incomplete. |
| `ingesting-prototypes` | The prototype scanner misses widgets created in loops. |
| Both | The Spotfire expressions in the Excel function map and Spotfire's rounding and null behaviour are not tested live. |

## spotfire-design

| Skill | Gap |
|---|---|
| `packaging-spotfire-apps` | The cover and Method page HTML templates follow the sanitizer rules but were not opened in Analyst. |
| `spotfire-app-design-rules` | KPI bands with label controls need manual steps, because the public API cannot add text-area controls. |

## spotfire-build

| Skill | Gap |
|---|---|
| `building-spotfire-dxps` | The standard engine does not build calculated columns, relations, hierarchies or band reference layers; the ingest drafts compute those columns in the data function, and anything else needs `--tier slim`. The manual-steps route (controls, triggers, theme, action-mod wiring) has not run in Analyst, so the menu paths it writes are unverified. `export_tables_job.py` and the slim tier after the cleanup have not run live. `ipy_parse.ps1` sometimes stops with a StackOverflowException; dxpgen then reports "IronPython parse not run" as a note. Visualization mods must already be embedded, installed or pinned. `scripts/sfgraph.py` is vendored from a local DXP toolkit whose authorship is to be confirmed. |
| `styling-spotfire-dxps` | The injector, theme JSON and tabs have not run in Analyst; the manual theme import route is unverified. |
| `writing-spotfire-ironpython` | The asset scripts have not run live. |
| `building-visualization-mods` | The layer-setup script has not run live. |
| `building-action-mods` | The example action scripts have not run live. Rollback when an action throws, `NeedsRefresh` after a failed run and the trigger depth cap are unverified. Publishing (library, pinning, package signing) is untested. |

## spotfire-testing

| Skill | Gap |
|---|---|
| `running-spotfire-unattended` | The runner DXP's "Run Pending Job" button is added by hand (public API only) and that step is not tested. `build_job.py` and `sfrun.py` are new. |
| `testing-dxps-through-the-ui` | No input commands were run during the release. Web Player testing through Playwright is not tested. `shotdiff`, `redact` and `uitest` need Pillow. |

## spotfire-version-control

| Skill | Gap |
|---|---|
| `setting-up-dxp-ci` | The self-hosted status and push jobs, the report job and the headless Claude Code workflow are untested. |
| `tracking-dxps-in-git` | IDE diff views and Git LFS are untested. dxpkit needs a license and a public home. |
| `updating-data-functions-with-claude` | Its runner scripts are copies of the `running-spotfire-unattended` scripts; `check_skills.py` keeps them identical. |

## spotfire-domain-context

| Skill | Gap |
|---|---|
| All | Pending SME review. |
| `analyzing-process-time-series` | Spotfire 15.0's bundled Python has no scipy, torch or scikit-learn and may lack pyyaml. The engine runs without scipy, but running it inside a Spotfire data function and on pandas 2.x is not tested. Regime bin widths and balance tolerances are design choices without a source. |
| `midstream-process-knowledge` | Only the crude pump station card comes from validated work. The amine treating, TEG dehydration, cryogenic NGL recovery and fractionation cards are drafts; their failure modes are marked UNVERIFIED. Two invariants (recovery in recovery mode only, separation against reflux) are left out because `requires_roles` cannot filter rows. |
| `generating-synthetic-process-data` | Realism targets are design choices without a source. |
| `analyzing-process-time-series`, `midstream-process-knowledge` | One citation (Liou 1998, used by the literature notes and the pump station card) is unverified. |
