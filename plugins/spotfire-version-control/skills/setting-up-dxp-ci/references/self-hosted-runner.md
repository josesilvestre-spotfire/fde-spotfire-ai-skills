# Self-hosted runner for DXP jobs

GitHub-hosted runners cannot read your analysis folders and have no Spotfire Analyst. Jobs that
need either run on a machine you register as a self-hosted runner.

## Which jobs need it

| Job | Needs | Runner OS |
|---|---|---|
| `status`, `push` (`dxp-sync.yml`) | read and write access to the DXP folders, dxpkit | any; Windows when the DXPs sit on a Windows share |
| `spotfire-report` (`data-functions-check.yml`) | Spotfire Analyst 15.0 signed in, the runner analysis built for the runner's account | Windows |
| `claude-data-function-request.yml` | the above plus Claude Code and the GitHub CLI (`gh`) | Windows |

## Register the runner

1. In the repository (or organization): **Settings > Actions > Runners > New self-hosted
   runner**, choose the OS and follow the download and `config` commands GitHub shows.
2. When `config` asks for labels, add `spotfire` (and keep the default `self-hosted` and OS
   labels). The workflows select `[self-hosted, spotfire]`, plus `windows` for Analyst jobs.
3. Run the runner as a service under an account that can read the DXP folders. For Analyst
   jobs, use an interactive account instead: Analyst needs a desktop session, a saved login and
   the runner analysis built under that account (see the `running-spotfire-unattended` skill).
   Script trust belongs to that account too.

## Environment

- Variables used in `dxpkit.yaml` (for example `ANALYSES`): set them in the runner's `.env` file
  in its install folder, or as job-level `env:` in the workflow.
- `DXP_WORKSPACE` for jobs that start Analyst.
- Install dxpkit for the runner's account (`python -m pip install <dxpkit source>`), and Python
  3.10 or newer.

## Operating rules

- A DXP that is open in Analyst cannot be replaced; `dxp push` reports an error for that target
  and leaves it untouched. Schedule merges when nobody has the analysis open, or rerun the job.
- Only one Analyst job runs at a time per account: the runner lock queues the next one.
- The runner machine is part of your trust boundary: workflows from forks must not run on it.
  In repository settings, require approval for workflows from outside collaborators, and keep
  self-hosted runners off public repositories.
