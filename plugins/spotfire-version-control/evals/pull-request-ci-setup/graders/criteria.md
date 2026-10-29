---
type: llm
weight: 1
---

Grade the files under `.github/workflows/`, `SETUP.md` and the response. Pass when all of these
hold; list every criterion that fails.

1. A validation job (`dxp validate`) runs on a GitHub-hosted runner for every pull request and
   needs no access to the share.
2. A status job runs on pull requests on a self-hosted runner selected with the label `spotfire`
   (`runs-on: [self-hosted, spotfire]` or with `windows` added) and fails when a DXP was edited
   in Spotfire (for example `dxp push --dry-run`, which passes on `git ahead` and fails on
   `spotfire ahead`, `conflict`, missing or untracked).
3. A push job runs on merge to main on the same runner, runs `dxp push` and commits
   `dxpkit.lock` with a `[skip ci]` style message; only that job gets `contents: write`.
4. dxpkit is installed from a repository variable such as `DXPKIT_PIP` that the team sets; the
   workflow refuses to run without it and does not vendor or copy dxpkit code into the repo.
   `ANALYSES` comes from the runner environment.
5. `SETUP.md` covers registering the runner with the `spotfire` label, the runner account's
   access to the share, making the validation and status jobs required checks, and warns that
   a DXP open in Analyst cannot be replaced.
6. It states that functions written by `dxp push` open untrusted until someone trusts them in
   Analyst (or a Script Author trusts them for everyone).
7. The Claude Code part keeps a person's approval: headless Claude validates, commits to a
   branch and opens a pull request, never promotes or merges; the rule lives in `CLAUDE.md`, and
   the run uses `--permission-mode auto`. No API key or token value appears in any file.
8. The response marks the self-hosted and Claude Code parts as untested templates or otherwise
   does not claim they were proven.
