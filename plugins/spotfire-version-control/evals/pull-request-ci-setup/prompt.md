---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write]
---

Our GitHub repository holds the Python data function scripts for about twenty Spotfire analyses
in `functions/`. `dxpkit.yaml` maps them to DXPs on a Windows file share through `${ANALYSES}`;
the DXPs are not in the repository. We have a Windows server that can reach the share.

Set up GitHub Actions so that every pull request is checked, a pull request cannot merge when a
DXP was changed in Spotfire behind our back, and a merge to main updates the DXPs. We would
also like Claude Code to pick up data function change requests from CI.

Write the workflow files under `.github/workflows/` and a `SETUP.md` with the steps we must do in
GitHub and on the server.
