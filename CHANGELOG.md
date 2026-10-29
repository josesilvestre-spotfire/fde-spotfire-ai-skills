# Changelog

## 0.1.0-alpha.1 (2026-10-29)

First test release, private repo.

- Seven plugins, 22 skills: Ingest (2), Design (3), Build (6), Testing and automation (2),
  Version control and CI/CD (4), Reference (1), Domain context (4).
- The planned Intake category is named Ingest. Its skills are `ingesting-prototypes` and
  `ingesting-excel-workbooks`; they write the App Brief, Logic Spec and draft build spec, and
  `building-spotfire-dxps` builds from them.
- Shared formats (App Brief, Logic Spec, naming standard) in the Reference plugin, with checked
  copies in the skills that use them.
- Eval cases for every plugin (`claude plugin eval`).
- Checks: Agent Skills spec, body size, shared-format copies, leak patterns, tests without
  Spotfire, generated docs.
- Left out: non-public Spotfire API calls and index, the Spotfire API index itself, dxpkit code,
  the program styling template script.
