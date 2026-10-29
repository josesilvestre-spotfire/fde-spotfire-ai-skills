---
title: Home
---

# Spotfire Skills Library (alpha)

Agent Skills for building, styling, testing and versioning Spotfire analyses (DXP files) with
Claude Code and other coding agents. 22 skills in seven plugins.

**Status: alpha, for testing.** Version `0.1.0-alpha.1`.

## Requirements

- Windows 10 or 11 and Spotfire Analyst 15.0 for building, running and testing DXPs.
- Python 3.10 or later for the bundled scripts.
- Git; dxpkit for the version-control plugin (installed from its own source).
- Claude Code for the plugin install, or any agent that reads Agent Skills.

## Install

```
/plugin marketplace add josesilvestre-spotfire/fde-spotfire-ai-skills
/plugin install spotfire-build@fde-spotfire-ai-skills
/plugin install spotfire-reference@fde-spotfire-ai-skills
```

| Plugin | Category |
|---|---|
| `spotfire-ingest` | Ingest: read prototypes and Excel workbooks, write the App Brief, Logic Spec and draft spec |
| `spotfire-design` | Design: App Brief framing, design rules, packaging |
| `spotfire-build` | Build: DXP builder, data functions, IronPython, styling, visualization and action mods |
| `spotfire-testing` | Testing and automation: unattended Analyst runs, UI tests |
| `spotfire-version-control` | Version control and CI/CD: data function updates, Git tracking, CI, audits |
| `spotfire-reference` | Reference: proven behaviour, naming standard, API index generator, shared formats |
| `spotfire-domain-context` | Domain context: process time series, midstream units, synthetic data, analytics models |

## Pages

- [Skills](skills.md): every skill with its description and alpha status
- [Bundled scripts](scripts.md): what each script does
- [Known gaps](known-gaps.md): what the alpha has not proven yet, by plugin and skill
- [Spotfire versions](spotfire-versions.md): which Spotfire versions each release was tested on
- [Library design](design.md): categories, shared documents, the Excel ingest stages, release plan
  and open decisions
