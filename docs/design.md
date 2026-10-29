---
title: Library design
---

# Spotfire Skills Library (Alpha): GitHub Repo and Pages Site

Status: alpha test release `0.1.0-alpha.1` in a private repo. Planned 10/26/2026, released for
testing 10/29/2026.

## 1. Purpose

This repo publishes the Spotfire skills used in our Claude Code environment. The skills cover
reading existing work, designing an analysis, building complete DXPs through the Spotfire API,
writing data functions and IronPython, styling, testing DXPs, and tracking them in Git.

Each skill is a standard Agent Skills folder (`SKILL.md` plus its files). The repo is a Claude
Code plugin marketplace, so a user installs it with two commands. The same folders work with
Claude.ai, the Claude API, and other agents (GitHub Copilot, Codex, Cursor) through
`npx skills` and the `AGENTS.md` file.

## 2. How the library is organized

The library has 22 skills in seven categories. Each category ships as one plugin, so a user
installs only the parts they need.

Two shared documents connect the categories:

- **App Brief:** business problem, users, decisions the app supports, KPIs, inputs, outputs, data
  sources, refresh cadence.
- **Logic Spec:** every calculation, with its equation and units.

The Ingest and Design skills write these documents and a draft build spec. The Build skills read
them. The Testing and Version control skills check and track what Build produces. The formats
live in the Reference plugin and every skill that uses them carries an identical copy.

| # | Category | Plugin | Purpose | Skills |
|---|---|---|---|---|
| 1 | Ingest | `spotfire-ingest` | Read existing work (prototypes, Excel workbooks) and write the App Brief, Logic Spec and draft build spec | 2 |
| 2 | Design | `spotfire-design` | Decide what the DXP must do for its users and how it behaves | 3 |
| 3 | Build | `spotfire-build` | Produce the DXP and its parts | 6 |
| 4 | Testing and automation | `spotfire-testing` | Run Spotfire unattended and test DXPs through the user interface | 2 |
| 5 | Version control and CI/CD | `spotfire-version-control` | Update, track, check and compare DXPs with Git | 4 |
| 6 | Reference | `spotfire-reference` | Lookups the other skills load when needed | 1 |
| 7 | Domain context | `spotfire-domain-context` | Engineering knowledge for understanding the goal and checking results | 4 |

## 3. Skills by category

### 3.1 Ingest

The Ingest skills read and document. They do not build. Each one ends by handing its files to
`building-spotfire-dxps`.

| Skill | What it does | Source |
|---|---|---|
| `ingesting-prototypes` | Reads a Shiny, Streamlit, Plotly, Quarto, HTML or React prototype and writes the App Brief, Logic Spec, a draft build spec and a mapping of every prototype element to its Spotfire element | DXP builder skill (prototype step and mapping notes) |
| `ingesting-excel-workbooks` | Breaks down an engineering workbook (structure, calculations, issues, goal), builds a Python model checked against Excel, and writes the App Brief, Logic Spec, draft build spec and change list. Ships the reconciliation script the build step uses. See section 4. | New |

To rebuild an existing DXP, inventory it first with `auditing-and-comparing-dxps` in category 5.

### 3.2 Design

| Skill | What it does | Source |
|---|---|---|
| `framing-spotfire-apps` | Writes the App Brief, starting with the business problem | Accelerator messaging standard and program notes |
| `spotfire-app-design-rules` | KPI bands built in HTML, marking drives every relevant visual, no empty visuals, filter panel limited to user columns, controls next to their visuals, separate data-generation tab, customer-ready text | Accelerator design rules, DXP builder lint rules and tests |
| `packaging-spotfire-apps` | App parts, page order, Method page, publishing checklist | Accelerator apps skill |

### 3.3 Build

| Skill | What it does | Source |
|---|---|---|
| `building-spotfire-dxps` | App spec, generated IronPython builder, saved DXP, verification report, versioned releases. Reads the Ingest and Design outputs. | DXP builder skill |
| `writing-spotfire-data-functions` | Python data functions: staging blocks, SBDF-safe types, registration tables, run chains, text columns as object dtype under pandas 3 | Data functions skill, data function update run |
| `writing-spotfire-ironpython` | IronPython 3.4 scripts: document properties, buttons, navigation, triggers | IronPython skill |
| `styling-spotfire-dxps` | Injector script, theme JSON, one host text area per page, HTML snippets that pass Spotfire's sanitizer, palette | Styling template kit (mechanism and measurements only), HTML text area skill |
| `building-visualization-mods` | Visualization mods: manifest rules, rendering, marking, test harness | Visualization mods skill |
| `building-action-mods` | Action mods: scripts, arguments, visual buttons, icons | DXP builder spec, action mod build notes |

### 3.4 Testing and automation

| Skill | What it does | Source |
|---|---|---|
| `running-spotfire-unattended` | Starts its own Analyst instance and leaves the user's open session alone. Runs builders and scripts as jobs, saves the DXP, renders every page, and takes a lock so runs do not collide. | DXP builder runner |
| `testing-dxps-through-the-ui` | Opens the analysis, clicks tabs, buttons and visuals, marks items, and takes a window screenshot after each step to confirm the result. Also captures and redacts documentation screenshots. | Desktop control skill, run checklists, article screenshot tools |

Rules this category carries:

- Windows only.
- Clicks and typing need an unsandboxed run; the sandbox drops input without an error.
- Screenshots capture a single window, so other applications on screen are never included.
- Unattended Claude Code runs on managed machines need `--permission-mode auto`.

### 3.5 Version control and CI/CD

| Skill | What it does | Source |
|---|---|---|
| `updating-data-functions-with-claude` | Edits the function file, applies it through the Spotfire API in a staging copy, runs it, renders the pages and writes a report. A person approves promotion, then the change is committed and pushed. | Data function update article and demo project |
| `tracking-dxps-in-git` | `dxp extract` into readable files, readable `git diff` for .dxp files, `dxpkit.yaml` mapping, `dxp status/push/pull`, a lock file that catches edits made inside Spotfire | dxpkit documentation |
| `setting-up-dxp-ci` | GitHub Actions: validation on GitHub-hosted runners for every pull request, status and push jobs on a self-hosted runner labelled `spotfire`, headless Claude Code settings with the approval step in `CLAUDE.md` | Demo repo CI workflow |
| `auditing-and-comparing-dxps` | Inventories pages, visuals, data functions, scripts and colors; compares two versions; checks a library folder against the design rules | DXP verification tools, audit material |

dxpkit is a prerequisite that users install from its own source. It is not distributed with this
library.

Script trust behavior these skills document (proven on Spotfire Analyst 15.0):

- A script set through the Spotfire API in the user's session is approved for that user.
- A dxpkit byte replacement keeps the old approval, so the function opens untrusted.
- Only the Script Author group can trust a script for every user.
- Web clients cannot grant trust.

### 3.6 Reference

| Skill | What it does | Source |
|---|---|---|
| `spotfire-reference` | Proven Analyst behaviors, naming standard, API index generator that runs against the user's own install, Excel function map, App Brief and Logic Spec formats | DXP builder reference folder, build notes |

### 3.7 Domain context

| Skill | What it does | Source |
|---|---|---|
| `analyzing-process-time-series` | Statistical analysis of historian data that accounts for operating regimes and autocorrelation; detects historian artifacts | Time series SME skill |
| `midstream-process-knowledge` | Unit cards for pump stations, NGL recovery, amine treating, dehydration, fractionation | Midstream process SME skill |
| `generating-synthetic-process-data` | First-principles simulators with event catalogs for demo and test data | Physics simulation engines skill |
| `process-analytics-models` | Regression suites, anomaly detection, forecasting, backtesting | ML analytics suites skill |

These skills make engineering claims. They ship in the alpha marked "Pending SME review".

## 4. Excel workbooks: ingest, then build

Engineers often build large, loosely organized calculation workbooks. `ingesting-excel-workbooks`
documents such a workbook, reproduces its calculations in Python, and writes the spec the DXP
builder uses. The Python model's code becomes the data function code, so the DXP ships the same
code that passed the comparison against Excel.

Stages 1 to 6 belong to `ingesting-excel-workbooks`. Stage 7 belongs to `building-spotfire-dxps`,
which runs the reconciliation script shipped by the ingest skill.

| Stage | Skill | Work | Output |
|---|---|---|---|
| 1. Inventory | Ingest | Open the workbook with macros disabled and links not updated. Read formulas, stored values, named ranges, tables, drop-down lists, conditional formats, hidden sheets, charts, pivots, external links, VBA, what-if tables. | Inventory file |
| 2. Structure | Ingest | Convert formulas to R1C1 notation so a filled-down column becomes one block. Classify cells. Build a dependency graph. Detect sheets copied from one template. | Block list, dependency graph |
| 3. Issues | Ingest | Find hardcoded constants in formulas, broken filled-down patterns, values typed over formulas, error values, circular references, OFFSET/INDIRECT, approximate lookups on unsorted data, unused calculations, mixed units. | Issue list with severity |
| 4. Meaning | Ingest | Describe each block with its equation and units, record the goal, users, decisions, inputs, outputs and manual steps. List questions for the owner. | HTML dossier. Checkpoint 1: owner confirms goal and logic |
| 5. Calculation model | Ingest | Port the Logic Spec to Python. Compare every output with Excel's values within a tolerance. | Model and reconciliation report. Checkpoint 2: every output matches or is explained |
| 6. Redesign | Ingest | Map each workbook element to a Spotfire element, write the App Brief, Logic Spec, draft build spec and change list. | Spec and change list. Checkpoint 3: owner approves the changes |
| 7. Build and verify | Build | `building-spotfire-dxps` builds the DXP from those files. The same reconciliation script checks the DXP outputs against Excel. | DXP and reconciliation report. Checkpoint 4 |

Rule: the DXP first reproduces the workbook's numbers within tolerance. Fixes to workbook errors
go in only after the owner approves them.

How workbook parts map to Spotfire:

| In the workbook | In the DXP |
|---|---|
| Raw data pasted into ranges | Data table loaded through a connection or SBDF |
| Row-level formula filled down a column | Calculated column |
| Running totals, lags, period-over-period comparisons | Calculated column with OVER, or a data function |
| Iteration, circular references, Goal Seek, Solver, matrices | Python data function |
| Input cells, scenario switches, drop-down lists | Document properties with text-area controls |
| Lookup tables | Joined or related tables, or a lookup in the data function |
| One sheet per well, case or month | One long table with an Asset or Case column, with trellis, filters and marking |
| What-if data tables | Data function that runs the sweep and writes a table |
| Charts, pivots, conditional formatting | Native visuals, cross tables, color rules |
| Summary or dashboard sheet | First page with an HTML KPI band |
| VBA macros | IronPython scripts or data functions behind buttons |

The Python port also matches Excel's own behavior: ROUND rounds half away from zero, the 1900
leap-year date bug, empty cells counting as 0, VLOOKUP defaulting to approximate match, 15
significant digits, and IFERROR hiding errors the port must report.

## 5. How other vendors publish skills

Checked 10/26/2026. Snowflake, Hex, Sigma, Qlik and Looker were not checked.

| Publisher | Install methods | Tests and evals | License |
|---|---|---|---|
| Anthropic (anthropics/skills) | Claude Code marketplace, Claude.ai, API | Template only | Apache-2.0 |
| dbt Labs (dbt-agent-skills) | Marketplace, npx skills, dbt deps | Eval comparison tool, tests, changelog | Apache-2.0 |
| Hugging Face (huggingface/skills) | Marketplace, Codex, Gemini CLI, Cursor, AGENTS.md | Metadata validation script | Apache-2.0 |
| ClickHouse (agent-skills) | npx skills, own CLI | None visible | Apache-2.0 |
| Posit (posit-dev/skills) | Marketplace grouped by category, npx skills | Token counter, stale-link finder | MIT |
| Vercel (agent-skills) | npx skills | A release for every skill change | MIT |
| Tableau (tableau-mcp) | MCP server (hosted, npx, Docker) | Unit, e2e and eval tests in CI | Apache-2.0 |
| Spotfire (spotfire-mods) | npm SDK | None visible | BSD-3 |

What this library adopts from these repos:

- Every skill passes the Agent Skills spec check: folder name matches `name`, no unsupported
  frontmatter keys such as `applyTo`.
- `npx skills` support and an `AGENTS.md` for non-Claude agents.
- An eval suite per plugin for `claude plugin eval`, which runs each test prompt with and without
  the plugin and reports the difference.
- Automated checks on every change: spec validation, personal-name and local-path check, token
  counts, tests that do not need Analyst.
- Tagged releases, a CHANGELOG and a version field in each plugin.
- SECURITY, CONTRIBUTING and AI usage policy files, and a list of what each bundled script does
  and where it writes.
- Skill names that describe the task (`writing-spotfire-data-functions`).
- The API index generated on the user's machine from their installed Analyst.
- A GitHub Pages site with a Spotfire version table, following spotfire-mods.

## 6. Repo contents

| Part | Contents |
|---|---|
| Install | `.claude-plugin/marketplace.json` listing the seven plugins, `npx skills` support, `AGENTS.md` |
| Plugins | `plugins/<plugin>/skills/<skill>/` with `SKILL.md`, `references/`, `scripts/`, `assets/` |
| Evals | `plugins/<plugin>/evals/<case>/` test prompts and graders per plugin |
| Examples | Synthetic data only, inside the skills that use them |
| Docs site | `docs/`: home with requirements and install steps, one entry per skill, scripts list, Spotfire version table, this design page |
| Automated checks | `scripts/check_skills.py` (spec, size, shared-format copies, leak patterns), `scripts/run_tests.py`, GitHub Actions workflow |
| Policy files | `SECURITY.md`, `CONTRIBUTING.md`, `AI-USAGE.md`. No license is granted during the alpha. |

## 7. Export from the local skills

The local skills stay the source and keep working as they do now. The public copy is a rewrite:

- Personal references become "you", local paths become environment variables (`SPOTFIRE_HOME`,
  `SPOTFIRE_PYTHON`, `DXP_WORKSPACE`), local skill numbers become public skill names, dated
  decision notes become plain rules.
- Leak check: `scripts/check_skills.py` fails on local paths, email addresses, tokens and the
  non-public API index. A private term list kept outside the repo adds personal names, customer
  and partner names and internal app names.
- One naming standard across all skills (`naming-standard.md` in the Reference plugin).

## 8. Release plan

| Release | Contents | Gate |
|---|---|---|
| `0.1.0-alpha.1` (this release) | All 22 skills in seven plugins, private repo, for testing | Leak check clean; tests that run without Analyst pass |
| Beta | Fixes from alpha testers | Clean-profile test, eval runs with and without the plugins, Excel skill on 2-3 real workbooks, UI tests on a second machine, review by one or two colleagues |
| 1.0, public | Same plugins | Decisions in section 9, security review of the trust content, SME review of the domain content |

Clean-profile test: a fresh Claude Code profile with no local skills or memory installs the
plugins from this repo and runs three prompts (restyle a DXP, write a data function, build the
well tear sheet). Pass means no reference to files or people that do not exist, the DXP opens,
and the verification report is clean.

## 9. Open decisions and blockers

| Item | Detail |
|---|---|
| GitHub org, visibility, license | spotfiresoftware org (next to spotfire-mods), a personal account, or internal only. BSD-3 matches spotfire-mods; Apache-2.0 is the most common among peers. |
| Spotfire Copilot team | spotfiresoftware/spotfire-copilot-docs documents an Agent Registry (A2A agents, MCP servers, skill reference). Agree how this repo relates to it before publishing, and keep "Copilot" out of the repo's naming. |
| Non-public Spotfire API | Left out of the alpha. The builder places HTML placeholders and writes a manual-steps checklist for text-area controls, property triggers and the document theme. Product and legal decide whether the internal route can ever be published. |
| Styling template ownership | The alpha ships an original injector and stylesheet. Confirm the author of the program template script and whether it can go out under the repo license. |
| dxpkit | Four skills depend on it. It needs the author's agreement, a license and a public home. |
| Trust content | Product security reviews the trust text before the repo is public. The skills keep the step where a person reviews and approves each change. |
| Excel test workbooks | 2-3 real engineering workbooks, ideally one hydraulics or production calculation and one economics model. |
| Python packages | oletools (reads VBA without opening Excel) and formulas (Excel calculation without Excel) are optional imports in the Excel skill. |
| Demo repo | The data function update demo repo sits on a personal GitHub account; it could move into the library's examples. |
