# Security

## What the bundled scripts do

The skills ship Python and PowerShell scripts. [docs/scripts.md](docs/scripts.md) lists every
script, what it does and where it writes. In summary:

- Scripts read the files you pass them (DXP, workbook, prototype, spec) and write into the app
  folder under `DXP_WORKSPACE` or a folder you name. None of them send data over the network.
- The build skills generate IronPython that you, or the unattended runner, run inside Spotfire
  Analyst. Read a generated builder before you run it; it runs with your Spotfire permissions.
- The testing skills start a separate Spotfire Analyst instance, send mouse and keyboard input to
  it and take screenshots of that window only. They never send input to other windows.
- The version-control skills commit and push only after a person approves the change.

## Script trust in Spotfire

Spotfire asks a person to trust a data function or script before it runs. The skills never
bypass that step. They document how trust behaves so that you know when Spotfire will ask again.

## Reporting a problem

Report a security problem privately to the repository owner through GitHub. Do not open a
public issue.
