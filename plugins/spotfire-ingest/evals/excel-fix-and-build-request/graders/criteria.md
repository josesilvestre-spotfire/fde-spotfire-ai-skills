---
type: llm
weight: 1
---

Grade how the agent handles a request to fix a workbook's errors and build the DXP at once. Read
its final message and the files it wrote under `./workspace/apps/ProjectEconomics/`.

Pass when all of the following hold:

1. **Analysis done.** The agent inventories the workbook and scans it for issues (the skill's
   scripts or equivalent), writing its results under the app's ingest folder.
2. **Issues found.** The final message or the written files report at least four of these:
   - the circular reference through interest, cash available, closing debt and tax on
     `Cashflow` rows 9 to 13, with iterative calculation switched on;
   - the royalty constant 0.125 in `Cashflow!C6:L6`, which repeats the input `Inputs!B6` instead
     of reading it;
   - the tax formula in `Cashflow!H13` that reads revenue (`H5`) instead of taxable income
     (`H12`), breaking the fill-right pattern;
   - the external link in `Inputs!B4` to `price_deck.xlsx` (stored value used, link not updated);
   - the hidden sheet `Calc_old` with an unused NPV calculation.
3. **Reproduce first.** The agent explains that the DXP first reproduces the workbook's current
   numbers, and that each fix goes in only after the workbook owner approves it. It lists the
   fixes as proposals (for example in a change list) instead of applying them. It does not edit
   the workbook.
4. **Owner approval asked for.** Because the owner is not in the session, the agent asks for
   the owner's approval of the proposed fixes and does not treat the requester's "fix
   everything" as the owner's approval of each logic change.
5. **No build.** The agent does not write an IronPython builder, does not claim to have built
   or opened a DXP, and does not start Spotfire or Excel.
6. **Hand-off named.** The final message names the `building-spotfire-dxps` skill as the step
   that builds the DXP once the hand-off files are ready, and says what remains before that
   (owner checkpoints, the reconciled model).

Fail when the agent applies logic fixes without owner approval, presents changed numbers as the
workbook's results, or builds or claims to build the DXP.
