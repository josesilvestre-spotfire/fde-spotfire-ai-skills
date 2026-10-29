# AGENTS.md

Instructions for coding agents (GitHub Copilot, Codex, Cursor, Gemini CLI and others) that use
this repo. Claude Code users install the plugins instead; see [README.md](README.md).

## Using the skills

- Every skill is a folder `plugins/<plugin>/skills/<skill>/` with a `SKILL.md`.
- Read a skill's `SKILL.md` when the task matches its `description`. Load files under its
  `references/` only when `SKILL.md` points to them for the step you are on.
- Run scripts from the skill's `scripts/` folder with the arguments `SKILL.md` gives. Do not edit
  them in place for one task.
- Read `plugins/spotfire-reference/skills/spotfire-reference/SKILL.md` before writing anything
  Spotfire will run; it indexes the proven behaviour, the naming standard and the shared formats.
- Keep every human approval step a skill describes: trusting scripts in Spotfire, promoting a DXP,
  and changing an owner's calculation logic.

## Skill index

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

## Changing this repo

- Follow [CONTRIBUTING.md](CONTRIBUTING.md).
- Run `python scripts/check_skills.py`, `python scripts/run_tests.py` and
  `python scripts/build_docs.py` before you commit.
