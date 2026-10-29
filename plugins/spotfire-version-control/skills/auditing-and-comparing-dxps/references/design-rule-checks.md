# Design-rule checks

`dxp_inventory.py check` runs these rules. Each finding has a level: FAIL blocks publishing,
WARN goes to the owner with the fix, INFO is for the record.

| Rule | Level | Finding | Why | Fix |
|---|---|---|---|---|
| `hygiene` | FAIL | a path under a Windows user folder in any text entry of the archive (the report shows it with the user name replaced) | data sources, mods and temporary import files keep the absolute path of the author's machine; it leaks the user name and breaks on every other machine | embed the data or load it from a shared location, re-add mods from the library, save again and re-check |
| `hygiene` | FAIL | a credential-like assignment (`password = '...'`, `token: "..."`) in a script, data function or text area | secrets in a DXP reach everyone who can open it | move the secret to a credentials profile or the server; rotate it |
| `empty-page` | FAIL | a page with no visuals | an unfinished page reaches users | remove the page or finish it |
| `no-kpi-chart` | WARN | a Spotfire KPI chart | KPI bands are built as HTML text areas, which keep a consistent style and can carry popups and details | replace with an HTML KPI band (see the `spotfire-app-design-rules` skill) |
| `visual-without-marking` | WARN | a data visual with no marking that is not limited by one | marking cannot start from it, so it breaks "marking drives every relevant visual" | set the marking used by the other visuals on its table |
| `mixed-markings` | WARN | visuals on one page and one table use different markings | a mark in one visual does not update the others | use one marking per table unless the design asks for two |
| `default-name` | WARN | a page, visual, data function or script that keeps a default name (`Page`, `Text Area`, `Untitled`, `New Script`, ...) | users and maintainers cannot tell the parts apart | name it after what it shows or does |
| `missing-description` | WARN | the analysis, or a data function, has no description | the library and the data function dialog show it to users | add one sentence on purpose and inputs |
| `no-trust-stamp` | INFO | a data function or script without an approval stamp | every user is asked to trust it | trust it once in Analyst (Manage trust) before publishing, or have a Script Author trust it |

## Rules that need more than the file

These design rules cannot be read from the archive. Check them through the UI
(`testing-dxps-through-the-ui` skill) or by review:

- No empty visuals: row counts of embedded tables are not readable without Spotfire.
- Marking updates every visual it should: the check above only finds visuals that cannot be
  marked at all.
- The filter panel shows only the columns users need.
- Controls sit next to the visuals they drive.
- Text is written for the customer, including code comments.
- A separate page for data generation, when the analysis generates data.

## Adjusting the rules

The rules are in the `check()` function of `dxp_inventory.py`. To add a rule, add a block that
calls `add(level, rule, where, message)` and a row to this table.
