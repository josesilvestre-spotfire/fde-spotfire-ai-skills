# Contributing and authoring standard

Every skill in this library follows the rules below. `scripts/check_skills.py` enforces the
mechanical ones on every change.

## Repo layout

```
.claude-plugin/marketplace.json        lists the seven plugins
plugins/<plugin>/
  .claude-plugin/plugin.json           name, version, description
  skills/<skill-name>/SKILL.md         one folder per skill
  skills/<skill-name>/references/      detail loaded only when needed
  skills/<skill-name>/scripts/         runnable code the skill calls
  skills/<skill-name>/assets/          templates, sample data, fixtures
  evals/<case>/prompt.md               eval cases for `claude plugin eval`
  evals/<case>/graders/*.md
docs/                                  GitHub Pages site
scripts/check_skills.py                spec, leak and size checks
```

## Skill format

- `SKILL.md` starts with YAML frontmatter. Required keys: `name`, `description`. Optional keys:
  `license`, `compatibility`, `metadata`, `allowed-tools`. No other keys (`applyTo` is rejected by
  the Claude.ai and API upload).
- `name` equals the folder name: lowercase letters, digits and single hyphens, at most 64
  characters.
- `description` is at most 1024 characters, written in the third person, and says what the skill
  does and when to use it.
- `metadata.maturity` records how far the skill has been tested: "Proven on one machine",
  "Assembled from proven parts, not run as a whole", or "New, not yet tested".
  `scripts/build_docs.py` copies it into the skill tables.
- Task skills use a gerund name that describes the task (`writing-spotfire-data-functions`).
  Knowledge skills use a noun phrase (`spotfire-reference`, `midstream-process-knowledge`).
- The `SKILL.md` body stays under 500 lines. Detail goes in `references/*.md`, linked from
  `SKILL.md` and kept one level deep.
- A skill works on its own. Refer to another skill by its name ("the `building-spotfire-dxps`
  skill"), never by a relative path into another skill's folder.

## Shared documents

The categories connect through files in one app folder:

```
$DXP_WORKSPACE/apps/<AppSlug>/
  app-brief.md      goal, users, decisions, KPIs, inputs, outputs, sources, refresh
  logic-spec.md     every calculation with its equation and units
  spec.json         build spec read by building-spotfire-dxps
  datafunctions/    Python data function code
  scripts/          IronPython scripts
  html/             text-area HTML
  data/             SBDF or CSV inputs
  ingest/           working files of the ingest skills (inventory, dossier, calc model,
                    reconciliation reports)
  versions/vX.Y/    releases written by building-spotfire-dxps
  versions/vX.Y/package/   publishing package written by packaging-spotfire-apps
```

- The ingest and design skills write `app-brief.md`, `logic-spec.md` and a draft `spec.json`.
- The build skills read them and never change the App Brief or Logic Spec without telling the
  user.
- The canonical formats are `app-brief-format.md`, `logic-spec-format.md` and
  `naming-standard.md` in `plugins/spotfire-reference/skills/spotfire-reference/references/`.
  A skill that writes or reads these documents carries a byte-identical copy in its own
  `references/` folder; the check script fails when a copy drifts.

## Environment variables

Skills never contain a local path. They use these variables and fall back to asking the user:

| Variable | Meaning |
|---|---|
| `SPOTFIRE_HOME` | Spotfire Analyst install folder (the folder that holds `Spotfire.Dxp.exe`) |
| `SPOTFIRE_PYTHON` | The `python.exe` Spotfire uses for Python data functions |
| `DXP_WORKSPACE` | Folder that holds `apps/`, `jobs/` and built DXPs |

## Writing

- Write for a Spotfire developer who has never seen this library. Address the reader as "you".
- Plain technical sentences. State the rule, then the reason in one line when it is not obvious.
- No slogans, storytelling, contrast framing or "from X to Y" phrasing. No marketing adjectives.
- No em or en dashes in prose. Use commas, colons or parentheses.
- No dated decision notes. Write the rule; history goes in `CHANGELOG.md`.
- Spotfire behaviour states the version it was proven on (Spotfire Analyst 15.0 unless noted).
- Anything not proven on a live Spotfire is marked **Not yet tested**.
- Code comments are written for a customer reading the code.

## No personal or internal content

Skills, scripts, examples and evals contain no:

- personal names, email addresses or Windows user names
- customer, prospect or partner names
- internal project or app names
- local paths (`C:\Users\...`, `Desktop\...`, `Downloads\...`)
- tokens, keys or server addresses
- the index of non-public Spotfire API classes, or code that calls them

Example data is synthetic.

## Checks

```bash
python scripts/check_skills.py                     # spec, size, copies, generic leak patterns
python scripts/check_skills.py --terms leak.txt    # plus a private list of names and terms
```

The private term list is kept outside the repo. Run the check with it before every push.

## Evals

Each plugin has 2 to 4 cases under `evals/`. A case is `prompt.md` (frontmatter: `max_turns`,
`allowed_tools`) plus `graders/*.md` (frontmatter: `type: llm`, `weight`). Run them with
`claude plugin eval plugins/<plugin>`; the command also runs a baseline without the plugin and
reports the difference.

## Releases

All plugins share one version while the library is in alpha. A release updates the version in
every `plugin.json` and in `marketplace.json`, adds a `CHANGELOG.md` entry and tags the commit
`v<version>`.
