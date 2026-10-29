# Headless Claude Code for DXP changes

## Permission mode

- Start unattended runs with `claude -p --permission-mode auto "<request>"`. In auto mode a
  classifier reviews each action within the organization's managed rules, so commands run
  without a prompt.
- A project cannot switch itself to auto mode through its settings file; use the command line
  flag.
- On machines where managed settings allow only managed permission rules, the `allow`, `ask`
  and `deny` rules in a project's `.claude/settings.json` (and in the user's settings) are
  ignored. A project therefore cannot pre-approve its own commands, and cannot force a
  question through an `ask` rule either.
- Without auto mode, every command outside the organization's rules asks for approval, which
  stalls a headless run.

## Where the approval step lives

Because project `ask` rules can be ignored, the human approval goes in `CLAUDE.md`:

- Interactive runs: Claude asks with the AskUserQuestion tool before `tools/promote.py`
  (`updating-data-functions-with-claude` skill).
- Headless runs: nobody can answer, so `CLAUDE.md` forbids promotion and tells Claude to open a
  pull request instead (`assets/claude/headless-section.md`). The review is the approval.

## Checking a run

`--output-format json` returns the run's result as JSON. Read:

- `permission_denials`: actions auto mode blocked. A denial of `tools/promote.py`, a push to the
  default branch or a merge is the expected outcome of the headless rules.
- the final message: the branch, the pull request and the report status.

## Launching from Git Bash on Windows

When a script starts a new Claude Code session from Git Bash:

- Set `MSYS_NO_PATHCONV=1`, otherwise Git Bash rewrites `/k` style arguments into paths.
- Clear `CLAUDECODE` and the `CLAUDE_CODE_SESSION_*` variables of the calling session.
- The first session in a new folder shows the folder trust prompt once; answer it before the
  first unattended run.
