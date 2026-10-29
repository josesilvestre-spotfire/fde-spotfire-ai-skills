# App Brief format

The App Brief records what a Spotfire analysis is for. The ingest and design skills write it; the
build skills read it. Save it as `app-brief.md` in the app folder (`$DXP_WORKSPACE/apps/<AppSlug>/`).

## Rules

- Start with the business problem the users have. Describe what the app does for them only after
  the problem is stated.
- Every KPI refers to a calculation ID in the Logic Spec (`L01`, `L02`, ...).
- Every input becomes a document property in the build spec.
- Every output names the page or visual that shows it.
- Open questions marked **Blocking** stop the build until the owner answers them or accepts the
  stated assumption.

## Template

```markdown
# App Brief: <App name>

Status: draft | confirmed by <role> on <date>
Source: <prototype path, workbook name, existing DXP, or interview>

## Business problem
<Two to four sentences: the problem, who has it, what it costs or risks today, how it is handled
now.>

## Users
| Role | What they do with the app | How often |
|---|---|---|

## Decisions the app supports
1. <Decision>: <what the user must see to make it>

## KPIs
| KPI | Logic Spec ID | Unit | Threshold or target | Shown on |
|---|---|---|---|---|

## Inputs
| Input | Type (number, choice, date, text, file) | Default | Range or choices | Set by |
|---|---|---|---|---|

## Outputs
| Output | Type (visual, table, export, alert) | Page | Used by |
|---|---|---|---|

## Data sources
| Source | Connection (file, database, API, SBDF) | Grain | Rows (approx.) | Owner |
|---|---|---|---|---|

## Refresh cadence
<On open, scheduled (interval), or on demand; who or what triggers it.>

## Out of scope
- <Item>

## Open questions
| # | Question | Blocking | Owner | Answer |
|---|---|---|---|---|
```
