---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write, Bash]
---

On our amine treating unit, contactor differential pressure went from about 4 psi to 9 psi
within two hours yesterday afternoon. Treated gas H2S rose from 2 to 6 ppmv over the same
period, the contactor level trend got noisy, and the operators added noticeably more amine
makeup than usual. Inlet gas rate was flat. Right now the lean amine is at 95 F and the inlet
gas is at 100 F.

What is the most likely explanation, what else could produce the same pattern, and what
should the operators check first? Then write the failure mode you think this is as a
unit-card YAML entry (with signature, onset, confounders, differentials, discriminators,
field checks and source) and save it as `foaming_mode.yaml`, so we can add it to our
monitoring.
