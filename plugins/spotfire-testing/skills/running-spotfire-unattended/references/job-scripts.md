# Job scripts

A job script is an IronPython 3 file that `runner_job.py` runs inside the unattended Analyst
process. Run one with:

```
python scripts/sfrun.py job my_job.py --set source=C:/analyses/example_analysis.dxp
python scripts/sfrun.py job my_job.py --json payload.json
```

## What the script receives

| Name | Content |
|---|---|
| `JOB` | dict from `job.json`: your `--set` and `--json` values plus `id`, `status`, `script` and `jobDir` |
| `Application` | the Analyst application |
| `Document` | the runner document. After `Application.Open(...)`, use `Application.Document` instead |
| `__name__` | `"__job__"` |

`json` imports normally: `runner_job.py` adds Analyst's IronPython library (`Lib.zip` under the
`Modules` folder of the install) to `sys.path` when needed.

## What the script must do

- Write every result as a file in `JOB["jobDir"]`. The folder exists before the script starts.
- Raise an exception on failure. `runner_job.py` catches it and writes the traceback to
  `result.json` with `status` `error`.
- Never save over `runner.dxp`. Open the analysis you work on with `Application.Open(path)`
  first; after that, `Application.SaveAs` writes the opened analysis.
- Use absolute paths.

## Rules proven on Analyst 15.0

- The script runs without a transaction (the runner's script has "Execute in transaction"
  off), so `Application.SaveAs` works inside it.
- `Application.Open(path)` inside a job replaces the runner document. The job script keeps
  running and works on the opened analysis through `Application.Document`.
- `visual.Render(graphics, page.GetVisualBounds(visual, Rectangle(0, 0, width, height)))`
  renders every visual of every page, including pages that are not active and while the
  window is off screen.
- A data function script set through `DataFunctionDefinitionBuilder` in the job's session is
  approved for the account that runs the job, so `ExecuteSynchronously()` runs it at once.

## Example: count rows in every table

```python
# count_rows.py: IronPython 3 job script for sfrun.py.
import json
from System.IO import File, Path

Application.Open(JOB["source"])
doc = Application.Document
counts = {t.Name: t.RowCount for t in doc.Data.Tables}
File.WriteAllText(Path.Combine(JOB["jobDir"], "row_counts.json"),
                  json.dumps(counts, indent=1))
```

```
python scripts/sfrun.py job count_rows.py --set source=C:/analyses/example_analysis.dxp
```

## The build job

`scripts/build_job.py` is the job behind `sfrun.py build` and `sfrun.py render`. Its `JOB` keys:
`analysis`, `builder`, `output`, `activePage`, `render`, `width`, `height`, `saveOnError`. Use it
as the model for your own jobs.
