# Spotfire Skills Library (alpha)

Agent Skills for building, styling, testing and versioning Spotfire analyses (DXP files) with
Claude Code and other coding agents.

**Status: alpha, for testing.** Version `0.1.0-alpha.1`. Private repo. The skills work on the
machine they were developed on; they have not yet been run from a clean profile or on a second
machine. Expect breaking changes before the beta. Each skill's status is in the table below;
what is not yet proven is listed in [docs/known-gaps.md](docs/known-gaps.md).

The library has 22 skills in seven plugins. Install only the plugins you need. The design is in
[docs/design.md](docs/design.md).

## Requirements

- Windows 10 or 11 for anything that runs Spotfire Analyst (build, unattended runs, UI tests).
  The ingest, design, reference and domain skills also work on macOS and Linux.
- Spotfire Analyst 15.0. Other versions are not yet tested; see
  [docs/spotfire-versions.md](docs/spotfire-versions.md).
- Python 3.10 or later for the bundled scripts. Data functions run in Spotfire's own Python.
- Git. The version-control plugin also needs dxpkit, which is not distributed with this library.
- Claude Code (recent version) for the plugin install and `claude plugin eval`.

Set these environment variables, or let the skills ask you:

| Variable | Meaning |
|---|---|
| `SPOTFIRE_HOME` | Spotfire Analyst install folder (the folder that holds `Spotfire.Dxp.exe`) |
| `SPOTFIRE_PYTHON` | The `python.exe` Spotfire uses for Python data functions |
| `DXP_WORKSPACE` | Folder that holds `apps/`, `jobs/` and built DXPs |

## Install

Claude Code:

```
/plugin marketplace add josesilvestre-spotfire/fde-spotfire-ai-skills
/plugin install spotfire-build@fde-spotfire-ai-skills
/plugin install spotfire-reference@fde-spotfire-ai-skills
```

Add the other plugins the same way (`spotfire-ingest`, `spotfire-design`, `spotfire-testing`,
`spotfire-version-control`, `spotfire-domain-context`). The repo is private, so Claude Code needs
your Git credentials for it; background updates need `GITHUB_TOKEN` set.

Other agents (GitHub Copilot, Codex, Cursor): `npx skills add
josesilvestre-spotfire/fde-spotfire-ai-skills`, or point the agent at [AGENTS.md](AGENTS.md).
Not yet tested against this private repo.

Claude.ai and the Claude API: upload a skill folder (`plugins/<plugin>/skills/<skill>/`) as a
zip.

## How the library fits together

```
Ingest  ->  Design  ->  Build  ->  Testing  ->  Version control
  writes      refines     reads       runs and     tracks, compares
  app brief,  the brief   them and    checks the   and promotes
  logic spec, and rules   builds the  DXP          the DXP
  draft spec              DXP
                Reference and Domain context are loaded by all of them
```

The categories share three files in one app folder (`$DXP_WORKSPACE/apps/<AppSlug>/`):
`app-brief.md` (the business problem, users, decisions, KPIs, inputs, outputs, sources),
`logic-spec.md` (every calculation with its equation and units) and `spec.json` (the build spec).
The formats are in the `spotfire-reference` plugin.

For an Excel workbook: `ingesting-excel-workbooks` inventories the workbook, ports its
calculations to Python, reconciles them against Excel and writes the three files.
`building-spotfire-dxps` then builds the DXP from them and runs the same reconciliation against
the DXP's outputs.

## Skills

<!-- skills:start -->
| Plugin | Skill | What it does | Alpha status |
|---|---|---|---|
| `spotfire-ingest` | [`ingesting-excel-workbooks`](plugins/spotfire-ingest/skills/ingesting-excel-workbooks) | Breaks down an engineering calculation workbook (.xlsx or .xlsm) without running it, documents its structure, calculations, issues and purpose, reproduces its ... | New, not yet tested |
| `spotfire-ingest` | [`ingesting-prototypes`](plugins/spotfire-ingest/skills/ingesting-prototypes) | Reads an app prototype (Shiny for Python, Streamlit, Plotly or Dash, Quarto, plain HTML or a React mockup) and writes the hand-off files for a Spotfire build, ... | New, not yet tested |
| `spotfire-design` | [`framing-spotfire-apps`](plugins/spotfire-design/skills/framing-spotfire-apps) | Writes the App Brief for a Spotfire analysis, starting with the business problem (who has it, what it costs, how it is handled today) before any capability, ... | New, not yet tested |
| `spotfire-design` | [`packaging-spotfire-apps`](plugins/spotfire-design/skills/packaging-spotfire-apps) | Packages a Spotfire analysis so that people other than its author can find, open, understand and trust it. | Assembled from proven parts, not run as a whole |
| `spotfire-design` | [`spotfire-app-design-rules`](plugins/spotfire-design/skills/spotfire-app-design-rules) | Applies the design rules for how a Spotfire analysis behaves for its users. | Assembled from proven parts, not run as a whole |
| `spotfire-build` | [`building-action-mods`](plugins/spotfire-build/skills/building-action-mods) | Builds and reviews Spotfire action mods (Spotfire 15.0, action API 2.5) in plain JavaScript. | Assembled from proven parts, not run as a whole |
| `spotfire-build` | [`building-spotfire-dxps`](plugins/spotfire-build/skills/building-spotfire-dxps) | Builds a finished Spotfire Analyst DXP from an app spec through Spotfire's public API. | Assembled from proven parts, not run as a whole |
| `spotfire-build` | [`building-visualization-mods`](plugins/spotfire-build/skills/building-visualization-mods) | Builds and reviews Spotfire visualization mods in plain JavaScript. | Assembled from proven parts, not run as a whole |
| `spotfire-build` | [`styling-spotfire-dxps`](plugins/spotfire-build/skills/styling-spotfire-dxps) | Styles Spotfire analyses (DXP files) without touching the filter panel or the data canvas. | New, not yet tested |
| `spotfire-build` | [`writing-spotfire-data-functions`](plugins/spotfire-build/skills/writing-spotfire-data-functions) | Writes and reviews Python data functions for Spotfire Analyst. | Proven on one machine |
| `spotfire-build` | [`writing-spotfire-ironpython`](plugins/spotfire-build/skills/writing-spotfire-ironpython) | Writes and reviews IronPython 3.4 scripts for Spotfire Analyst documents. | Assembled from proven parts, not run as a whole |
| `spotfire-testing` | [`running-spotfire-unattended`](plugins/spotfire-testing/skills/running-spotfire-unattended) | Runs IronPython builders and job scripts in a separate, unattended Spotfire Analyst instance on Windows, saves the resulting DXP and renders every page to PNG, ... | Assembled from proven parts, not run as a whole |
| `spotfire-testing` | [`testing-dxps-through-the-ui`](plugins/spotfire-testing/skills/testing-dxps-through-the-ui) | Tests a Spotfire DXP through the Analyst user interface on Windows. | Assembled from proven parts, not run as a whole |
| `spotfire-version-control` | [`auditing-and-comparing-dxps`](plugins/spotfire-version-control/skills/auditing-and-comparing-dxps) | Audits Spotfire DXP files without opening Spotfire. | Proven on one machine |
| `spotfire-version-control` | [`setting-up-dxp-ci`](plugins/spotfire-version-control/skills/setting-up-dxp-ci) | Sets up GitHub Actions for Spotfire DXPs whose data function scripts are tracked in Git. | Assembled from proven parts, not run as a whole |
| `spotfire-version-control` | [`tracking-dxps-in-git`](plugins/spotfire-version-control/skills/tracking-dxps-in-git) | Tracks Spotfire DXP files and their data function scripts in Git with dxpkit. | Proven on one machine |
| `spotfire-version-control` | [`updating-data-functions-with-claude`](plugins/spotfire-version-control/skills/updating-data-functions-with-claude) | Updates the Python script of a Spotfire data function from a Git project. | Assembled from proven parts, not run as a whole |
| `spotfire-reference` | [`spotfire-reference`](plugins/spotfire-reference/skills/spotfire-reference) | Lookups for Spotfire Analyst work. | Assembled from proven parts, not run as a whole |
| `spotfire-domain-context` | [`analyzing-process-time-series`](plugins/spotfire-domain-context/skills/analyzing-process-time-series) | Analyzes process and pipeline historian time series with a tested Python engine (tssme) that conditions every comparison on operating regime, corrects ... | Proven on one machine |
| `spotfire-domain-context` | [`generating-synthetic-process-data`](plugins/spotfire-domain-context/skills/generating-synthetic-process-data) | Generates synthetic process historian data from first principles for demos, tests and anomaly-detection training sets, using a three-layer simulator ... | Assembled from proven parts, not run as a whole |
| `spotfire-domain-context` | [`midstream-process-knowledge`](plugins/spotfire-domain-context/skills/midstream-process-knowledge) | Provides process engineering knowledge for midstream oil and gas units as YAML unit cards plus a process reference, covering crude pump stations (validated ... | Pump station card proven on one machine; four draft cards new, not yet tested |
| `spotfire-domain-context` | [`process-analytics-models`](plugins/spotfire-domain-context/skills/process-analytics-models) | Builds and reviews analytics models for process and production data that are delivered as Spotfire data functions, including interpretable regression suites ... | Assembled from proven parts, not run as a whole |
<!-- skills:end -->

## What this alpha leaves out

- **Non-public Spotfire API.** Text-area controls, property-change triggers, the document theme,
  action-mod wiring and Spotfire's own HTML sanitizer have no public API in Spotfire 15.0. The
  builder places HTML placeholders, writes the manual steps to `build/MANUAL-STEPS-<tier>.md`, and
  checks text-area HTML with its own sanitizer emulation.
- **Spotfire API index.** You generate it from your own Analyst install with the generator in
  `spotfire-reference`; no index ships in the repo.
- **dxpkit.** Four version-control skills use it. Install it from its own source.
- **Program styling template.** `styling-spotfire-dxps` ships an original injector and stylesheet
  that use the same mechanism.

## Open items before a public release

| Item | Detail |
|---|---|
| Org, visibility, license | No license is granted during the alpha. BSD-3-Clause (as spotfire-mods) or Apache-2.0 is decided before the repo goes public. |
| Spotfire Copilot team | Agree how this library relates to the Spotfire Copilot Agent Registry before publishing. |
| Non-public API | Product and legal decide whether the internal route can ever be published. |
| Styling template | Confirm the template script's author and license. |
| dxpkit | Author's agreement, a license and a public home. |
| Trust content | Security review of the script trust text in the version-control skills. |
| Domain content | SME review of the domain context plugin. |
| Excel ingest | Run on 2-3 real engineering workbooks. |
| Clean-profile test | Fresh Claude Code profile, three prompts, eval runs with and without the plugins. |

## Checks

```bash
python scripts/check_skills.py     # spec, sizes, shared-format copies, leak patterns
python scripts/run_tests.py        # tests that do not need Spotfire
python scripts/build_docs.py       # regenerate the skill tables and docs pages
claude plugin validate .           # marketplace and plugin manifests
claude plugin eval plugins/spotfire-build   # evals, with and without the plugin
```

The same checks run in GitHub Actions on every push and pull request. Authoring rules are in
[CONTRIBUTING.md](CONTRIBUTING.md); script behaviour is in [SECURITY.md](SECURITY.md) and
[docs/scripts.md](docs/scripts.md).
