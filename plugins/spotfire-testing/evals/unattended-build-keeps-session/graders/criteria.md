---
type: llm
weight: 1
---

Grade `run-plan.md` and the response. Pass when all of these hold; list every criterion that
fails.

1. The build runs in a new, separate Analyst process started by the runner (for example
   `sfrun.py build ... --out ...`), not in the user's open session. The plan never attaches to,
   clicks into, saves or closes the user's Analyst window or `production_review.dxp`.
2. The plan checks the runner setup first (`sfrun.py check` or equivalent: `DXP_WORKSPACE`,
   `runner.dxp`, `blank.dxp`, Analyst found) and says the one-time runner build in Analyst is a
   step for the user, not something done during the meeting.
3. The builder runs against a blank base and the output is saved with an absolute path; every
   page is rendered to PNG by Spotfire's own render, not by screen capture.
4. The plan reads the result files (job status, build result, builder output) and opens every
   page render before reporting success, noting that a builder can finish without error and
   still leave an empty visual.
5. The plan mentions the lock that keeps runs from colliding, and that the runner sends no
   clicks or keys (so no unsandboxed input is needed for this job).
6. Failure handling: a login dialog (sign in once with a saved login), a runner that does not
   pick up the job (trust or button check), a held lock (`lock status` / `lock recover`, which
   ends only the job's own Analyst process). It never closes the user's Analyst processes.
7. If the plan runs Claude Code unattended, it uses `--permission-mode auto` (or explains why a
   managed machine needs it). It does not invent Spotfire command-line switches that run
   scripts.
