---
name: testing-dxps-through-the-ui
description: Tests a Spotfire DXP through the Analyst user interface on Windows. Opens the analysis in its own Analyst instance, clicks tabs, buttons and visuals, marks items, takes a window-only screenshot after each step and checks the result, for example that a marking updates every visual it should. Also captures, crops and redacts screenshots for documentation. Use when a built or changed DXP must be checked the way a user works with it, or when documentation screenshots of an analysis are needed.
compatibility: Windows with Spotfire Analyst 15.0 and Python 3.10 or newer; Pillow for screenshot comparison and redaction. Clicks and typing need an unsandboxed run. Proven on one machine.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Testing DXPs through the UI

You drive a separate Analyst window with real mouse and keyboard input, take a screenshot of
that window after every step, and confirm each step from the screenshot before the next one.

## Rules

- **Windows only.**
- **Unsandboxed input.** `click`, `dclick`, `rclick`, `drag`, `wheel`, `type`, `keys`, `selftest`
  and `uitest.py run` send real input. Inside the Bash sandbox Windows drops that input and the
  command still reports success. Run them with the sandbox disabled, and tell the user first:
  the approval prompt and the takeover of the mouse both affect them. `wins`, `spotfire`,
  `browser`, `place` and `shot` work in the sandbox.
- **A command's success proves nothing.** Take a screenshot after every action and read it.
- **Window-only screenshots.** `deskctl.py shot` uses PrintWindow, so the image holds the target
  window only, even when another window overlaps it. Never grab the full screen or a screen
  region: a region grab once captured a chat window that sat on top of the target.
- **Own instance, test copy.** Copy the DXP to a test folder and open the copy with
  `deskctl.py spotfire`, which starts a new Analyst process. Never click into, capture or close
  an Analyst window the user opened. `deskctl.py close` refuses a process it did not start.
- **Ask before you take over the mouse.** Input runs while the user may be working. Do not run
  during a meeting or screen share. Group input into as few commands as you can.
- **Unattended Claude Code on a managed machine** needs `claude --permission-mode auto`.

For builds and renders that need no clicks, use the `running-spotfire-unattended` skill: it
sends no input and works without the sandbox exception.

## The loop

```
python scripts/deskctl.py spotfire C:/ui-tests/example_analysis.dxp   # prints: pid hwnd
python scripts/deskctl.py place <hwnd> 40 40 1600 1000
python scripts/deskctl.py shot <hwnd> C:/ui-tests/run-01/00-start.png
```

1. **Open** the copy in a new Analyst process. Wait for the analysis to finish loading.
2. **Place** the window at a fixed size, so coordinates stay valid between runs.
3. **Shot** and read the image. Pixel (x, y) in the image is the (x, y) you pass to `click`:
   both are window coordinates in physical pixels.
4. **Act:** click a tab, a button or a mark; drag to mark a range; type into an input control.
5. **Shot** again and confirm the step worked before you go on.
6. **Close** the process you started: `python scripts/deskctl.py close <pid>`.

The first click after an analysis opens is sometimes absorbed (seen on Analyst 15.0). Start a
test with a click on an empty part of the page.

## Check that a marking reaches every visual

1. Take a start screenshot and note one box per visual: `[left, top, right, bottom]` in window
   pixels.
2. Mark items in one visual (a click on a bar, a drag over points).
3. Take the next screenshot and compare:

   ```
   python scripts/shotdiff.py 00-start.png 01-mark.png --box bars=890,480,1590,960
          --box table=890,150,1590,470 --box trend=10,150,880,960 --out 01-diff.png
   ```

   Each visual the marking should update must show changed pixels; a visual on an unrelated
   table must not. Then read `01-diff.png` (changed pixels tinted red) and the screenshot itself:
   the numbers prove that something changed, the image shows whether it is the right change.

To run a whole sequence, write a plan and run it:

```
python scripts/uitest.py validate plan.json
python scripts/uitest.py run plan.json
```

The plan names the analysis, the window size, the boxes and the steps with their expected
changed and unchanged boxes. `uitest.py` takes a screenshot after every step and writes
`REPORT.md` with PASS or FAIL per step. Format and an example:
[references/test-plan-format.md](references/test-plan-format.md) and
`assets/example-plan.json`.

## What to test in a DXP

[references/what-to-test.md](references/what-to-test.md) lists the checks per element (pages,
marking, filters, buttons and scripts, property controls, popups and details) and the Analyst
15.0 behaviours that affect a test.

## Documentation screenshots

Take the screenshot with `deskctl.py shot`, then crop and redact it before it leaves the
machine:

```
python scripts/redact.py apply 03-result.png doc-result.png --crop 10,38,1590,990
       --pixelate 120,8,420,30 --fill 1300,8,1590,30
python scripts/redact.py combine doc-before-after.png before.png after.png --gap 24
```

Rules for what to remove are in [references/screenshots.md](references/screenshots.md).

## Check the setup

Run `python scripts/deskctl.py selftest` unsandboxed when input seems not to arrive. It opens
`assets/selftest.html` in a new Chrome or Edge window, clicks into the text box, types a sentence,
takes before and after screenshots and closes the tab. Read `after.png`: the sentence must be in
the box.

## Proven and not yet tested

Proven on one Windows machine: window-only PrintWindow capture, clicks and typing from an
unsandboxed run, input dropped silently inside the sandbox, the selftest loop, the crop and
pixelate steps for published screenshots.

**Not yet tested:** `uitest.py run` and `shotdiff.py` against a live Analyst window (both were
run on synthetic images only); `deskctl.py spotfire` (the launch code comes from the proven
runner); Web Player testing through the Playwright MCP tools has not been tried.
