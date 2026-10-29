# What to test in a DXP

Work through the analysis the way its users do. For each page, take a screenshot, then test the
elements below. Record each check with its screenshot.

## Pages

- Every page tab opens, shows its title and has no empty visual. An empty visual or a "no data"
  message usually means a broken binding or a data function that did not run.
- Text areas render (KPI bands, headers, help text) with no raw HTML or placeholder text.

## Marking

- Marking in each visual updates every visual it should: the visuals on the same table, on
  related tables, and details visuals limited by that marking.
- Visuals on unrelated tables do not change.
- A click on empty plot area clears the marking; check that every visual returns to its start
  state.

## Filters

- The filter panel shows only the columns users need.
- Changing a filter updates the visuals on that table and leaves others alone.

## Buttons, scripts and data functions

- Each button runs its script or data function. Confirm the visible result (a page change, new
  output rows, a property value in a text area).
- A data function that runs on a button needs a `wait` step when it takes longer than a few
  seconds.
- A script or data function that is not trusted for the current user does not run. If a button
  does nothing, check File > Manage trust on the test account.

## Property controls

- Drop-downs, inputs and sliders change their document property, and the visuals or data
  functions that use the property update.

## Analyst 15.0 behaviours that affect a test

- The first click after an analysis opens is sometimes absorbed. Start with a click on an empty
  part of the page.
- A click on a graphical-table row header does not mark the row.
- A scatter plot line connection cannot be clicked; click the markers.
- Visual title-bar buttons show only for action-mod scripts, never for IronPython scripts.
- A drop-down inside a hidden (`display:none`) section of a text area renders zero wide.
- Closing the script editor with Cancel undoes the script's changes in the open analysis.
  Never test by running scripts in the editor of the analysis under test.

## Web Player

Testing the same analysis in Spotfire Web Player through the Playwright MCP tools works on page
elements instead of pixels. **Not yet tested.**
