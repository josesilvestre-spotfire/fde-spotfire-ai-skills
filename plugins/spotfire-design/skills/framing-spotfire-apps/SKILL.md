---
name: framing-spotfire-apps
description: Writes the App Brief for a Spotfire analysis, starting with the business problem (who has it, what it costs, how it is handled today) before any capability, then users, decisions, KPIs, inputs, outputs, data sources and refresh cadence. Interviews the app owner with a fixed question set, reserves Logic Spec IDs for every KPI, and checks the brief before the build starts. Use it when someone asks for a new Spotfire app, dashboard or analysis, when an idea or a generic capability (anomaly detection, forecasting, a time series toolkit) needs a business problem, or when an App Brief written by an ingest skill must be completed and confirmed with its owner.
metadata:
  maturity: New, not yet tested
---

# Framing Spotfire apps

You write `app-brief.md` for one Spotfire analysis. The brief says which business problem the
analysis solves for which users, before it says anything about Spotfire features. The build skills
read it, so every KPI, input and output in it must be specific enough to build and test.

Format: [references/app-brief-format.md](references/app-brief-format.md) (canonical copy of the
library format). KPIs point to calculation IDs in the Logic Spec:
[references/logic-spec-format.md](references/logic-spec-format.md).

## When to use it, and what comes before

- A request for a new app, dashboard or analysis: start here.
- A prototype or Excel workbook exists: run the `ingesting-prototypes` or
  `ingesting-excel-workbooks` skill first. They write a draft brief and Logic Spec; you complete
  the brief with the owner.
- A generic capability with no named problem ("an anomaly detection app", "a forecasting
  workbench"): start here and find the business problem before anything else.

This skill writes documents. It does not build a DXP.

## Workflow

1. **Locate the app folder.** `$DXP_WORKSPACE/apps/<AppSlug>/`, where `AppSlug` is the app name in
   PascalCase (`HeatExchangerFoulingReview`). If `DXP_WORKSPACE` is not set, ask the user where the
   app folder is. If `app-brief.md` exists, read it and refine it: keep its `Source` line, and tell
   the user before you remove or change anything the owner already confirmed.
2. **Read what exists.** Notes, emails pasted by the user, a prototype, a workbook, an existing DXP,
   the ingest skills' output. List what you learned and what is missing, by brief section.
3. **Interview the owner.** Ask the questions in
   [references/interview-questions.md](references/interview-questions.md), the business problem
   group first. Ask three to five questions per round, in the order of the file. Do not propose
   pages, visuals or features until the business problem is stated and agreed. When the user
   cannot reach the owner, write your best assumption into the brief and add an open question.
4. **Frame the problem** (rules below).
5. **Write `app-brief.md`** from the template, sections in template order, `Status: draft`.
6. **Reserve Logic Spec IDs.** Every KPI needs an ID. If `logic-spec.md` exists, use its IDs and
   never renumber them. Otherwise create it from the Logic Spec template with one entry per KPI:
   name, the equation as far as you know it, units, `Status: inferred`. The ingest and build skills
   complete it.
7. **Run the checks** below. Fix what you can; turn the rest into open questions.
8. **Hand over.** Show the user the brief, the blocking questions and the assumptions. The status
   becomes `confirmed by <role> on <date>` only when the owner confirms it. Next steps: the
   `spotfire-app-design-rules` skill for how the app behaves, then `building-spotfire-dxps`.

A worked example: [references/example-brief.md](references/example-brief.md) (synthetic heat
exchanger fouling app).

## Framing rules

- **The first sentence names the problem and who has it.** "Maintenance planners learn that a
  heat exchanger has fouled only when ..." It contains no product, technique or feature name
  (Spotfire, dashboard, machine learning, anomaly detection, time series, AI).
- **Say what it costs or risks today, with a number** (hours per week, events per year, money per
  event, barrels, downtime) or a named consequence (a missed regulatory report, a safety limit).
  Use the owner's numbers; when they have none, write an order of magnitude and mark it as an
  assumption in the open questions.
- **Say how it is handled today** (a monthly spreadsheet, a manual historian export, nobody looks
  until an alarm). That is the baseline the app must beat.
- **One business problem per brief.** A generic capability that serves several problems becomes
  one brief per problem (equipment reliability, production interruptions, process upsets, metering
  differences). The apps can share most of their content; each one leads with its own problem,
  users and KPIs.
- **Name the app after the problem domain**, in the users' words: "Heat Exchanger Fouling Review",
  not "Time Series Anomaly Toolkit". Use the same name everywhere afterwards.
- **Users run it on their own data.** Assume the users will bring their own data, not only the
  demo set. Record the data they must supply (tables, required columns, grain) under Data sources,
  and add the data file or connection as an input. The build then includes a staging step that
  maps their columns.
- **Inputs are decisions a user can make.** A setpoint, a threshold, a price, a schedule, an asset
  choice. Settings that only shape demo or generated data (random seed, noise level, simulated
  events, calibration constants) go in the Inputs table with `Set by: advanced user (Data
  Generation page)` so the design step keeps them off the working pages.
- **Few KPIs, each tied to a decision.** Three to six KPIs. Each one has a unit, a threshold or
  target, and the page that shows it. A KPI that no decision uses is an output, not a KPI.
- **Out of scope is explicit.** Name what this release does not do, especially what someone is
  likely to ask for next. When you drop an item to meet a date, add it here.
- **Write for the owner.** Plain sentences, the users' units and terms, no internal project
  names, no version history.

## Checks a brief must pass

Run every check before you hand the brief over. Report each failure with its fix, or record it as
an open question.

| # | Check | How to check |
|---|---|---|
| 1 | The business problem comes first and names who has it | The first sentence of "Business problem" names a role or group and a problem. No product, technique or feature word in it. |
| 2 | The cost or risk is stated | The section has a number with a unit, or a named consequence, plus how it is handled today. |
| 3 | Every user has a decision | Each role in Users appears in at least one decision, or the role is removed. |
| 4 | Every decision has evidence | Each decision says what the user must see, and that item is a KPI or an output. |
| 5 | Every KPI is complete | Logic Spec ID present in `logic-spec.md`, unit, threshold or target, page. |
| 6 | Every input is buildable | Type, default, range or choices, and who sets it. Defaults sit inside their range. |
| 7 | Generator and calibration settings are marked | Each is set by "advanced user (Data Generation page)". |
| 8 | Every output is placed | Type, page and the role that uses it. |
| 9 | Data sources are concrete | Connection type, grain, approximate rows, owner. The data users must bring is listed with its required columns. |
| 10 | Refresh is stated | On open, scheduled (interval) or on demand, and who or what triggers it. |
| 11 | Scope is bounded | At least one Out of scope item. |
| 12 | Open questions are honest | Every assumption made without the owner is an open question; questions that stop the build are marked **Blocking**; no blocking question is open when the status is `confirmed`. |
| 13 | Names and units are consistent | One app name; page names reused exactly between KPIs, Inputs and Outputs; one unit system as in the Logic Spec conventions. |
| 14 | The text is customer-ready | No internal project names, person names, version tags or TODO notes. |

## Hand-off notes

- The build skills turn every input into a document property and every output into a page or
  visual. Write inputs and outputs so they can be counted.
- The `packaging-spotfire-apps` skill takes the cover page text from the business problem, so
  keep its first two sentences short enough to stand on their own.
- Changing a confirmed brief later is a change for the owner to approve. Record what changed and
  why in the brief's open questions table, with the answer column filled in.
