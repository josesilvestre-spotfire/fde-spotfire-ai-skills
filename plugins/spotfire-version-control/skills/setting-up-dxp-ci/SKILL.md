---
name: setting-up-dxp-ci
description: Sets up GitHub Actions for Spotfire DXPs whose data function scripts are tracked in Git. Validation runs on GitHub-hosted runners for every pull request; status and push jobs run on a self-hosted runner labelled spotfire that can reach the DXPs; headless Claude Code runs keep the human approval step in CLAUDE.md. Ships workflow templates with placeholders. Use when a user wants pull request checks, required status checks or automated syncing for DXP data functions, or wants Claude Code to handle change requests from CI.
compatibility: GitHub Actions; dxpkit installed separately; a self-hosted runner (Windows for any job that starts Spotfire Analyst 15.0). Partly proven on one repository.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Setting up DXP CI

Three workflow templates in `assets/workflows/`, for two project layouts:

| Template | Layout | Jobs |
|---|---|---|
| `dxp-sync.yml` | DXPs live outside the repository (a share or folder the runner reads); `dxpkit.yaml` points at them through `${VARS}` | `validate` (GitHub-hosted, every pull request), `status` (self-hosted `spotfire`, every pull request), `push` (self-hosted `spotfire`, on merge) |
| `data-functions-check.yml` | DXPs committed in `analyses/`; changes applied with the `updating-data-functions-with-claude` tools | `check` (GitHub-hosted, every push and pull request), optional `spotfire-report` (self-hosted Windows with Analyst) |
| `claude-data-function-request.yml` | either | a person starts it with a request; headless Claude Code edits, validates and opens a pull request; it never promotes |

Copy the ones you need to `.github/workflows/` and replace every `<...>` placeholder.

## Rules

- **dxpkit is a prerequisite, not part of this library.** Set the repository variable
  `DXPKIT_PIP` to the argument pip uses to install dxpkit from its own source (a Git URL or a
  package index name your organization hosts). The workflows refuse to run without it, so CI
  never installs an unrelated package of the same name.
- **A person approves every promotion.** In CI that person is the pull request reviewer. No
  workflow here promotes a staging copy or merges by itself. Keep it that way when you adapt
  them.
- **Pushed functions are untrusted.** The `push` job writes script bytes into the DXPs with
  `dxp push`; Spotfire then treats the function as untrusted until someone trusts it in Analyst
  (File > Manage trust > Review > Trust, refresh, save). Say so in the pull request template, or
  use the `data-functions-check.yml` layout, where the change is applied through the Spotfire
  API before it is committed.
- **Least privilege.** Workflows default to `contents: read`; only the job that commits gets
  `contents: write`.
- **Headless Claude Code** on a managed machine needs `--permission-mode auto`, and the
  approval rule must be in `CLAUDE.md`: managed settings can make Claude Code ignore a project's
  allow and ask rules.

## Steps

1. **Track the scripts** with dxpkit (`tracking-dxps-in-git` skill): `dxpkit.yaml`,
   `dxpkit.lock` and the sources in `functions/` are committed.
2. **Set `DXPKIT_PIP`** under Settings > Secrets and variables > Actions > Variables.
3. **Add the workflow** for your layout.
4. **Self-hosted runner** (for `status`, `push`, `spotfire-report` and the Claude workflow):
   register it with the label `spotfire` and give it access to the DXP folders. Details:
   [references/self-hosted-runner.md](references/self-hosted-runner.md).
5. **Required checks:** in the branch protection rule for the default branch, require
   `validate` and `status` (`dxp-sync.yml`) or `check` (`data-functions-check.yml`).
6. **Claude Code requests (optional):** add the section in `assets/claude/headless-section.md`
   to the project's `CLAUDE.md`, store the API key as a repository secret, and add
   `claude-data-function-request.yml`.

## What each check catches

- `dxp validate`: a broken `dxpkit.yaml`, an `.sfd` source that does not parse, a Python syntax
  error in any tracked script.
- `dxp status` (in-repo layout): a script changed in Git but not applied to the committed DXP
  (`git ahead`, exit code 1). Proven: a commit with only the script change failed this check;
  the commit that also carried the applied and promoted analysis passed.
- `dxp push --dry-run` (sync layout): a DXP edited in Spotfire since the last sync
  (`spotfire ahead`, `conflict`), a missing target or an untracked difference. A pull request
  that only changes scripts in Git passes (`git ahead` is the expected state before merge).

## Headless Claude Code

`claude -p --permission-mode auto --output-format json "<request>"` runs one request without a
person at the keyboard. Read `permission_denials` in the JSON output to see what auto mode
blocked. The headless section of `CLAUDE.md` tells Claude to validate in staging, commit the
script and report to a branch and open a pull request, and never to promote. The reviewer
approves the pull request, then promotes with `tools/promote.py` and commits the analysis.
[references/headless-claude.md](references/headless-claude.md) has the settings and the
reasons.

## Proven and not yet tested

Proven on one GitHub repository: `validate` on a GitHub-hosted runner for a pull request; the
in-repo `check` job (validate and status) failing on a script-only commit and passing once the
applied analysis was committed; `dxp push`, `dxp pull` and the lock commit run locally.
Claude Code in auto permission mode ran the whole local update with one approval.

**Not yet tested:** the `status` and `push` jobs on a self-hosted runner (in the proven
repository no runner was registered, so `status` stayed queued); `spotfire-report`;
`claude-data-function-request.yml` and the headless `CLAUDE.md` section.
