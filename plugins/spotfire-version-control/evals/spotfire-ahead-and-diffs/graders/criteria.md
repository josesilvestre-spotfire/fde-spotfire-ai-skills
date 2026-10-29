---
type: llm
weight: 1
---

Grade `answer.md`, `.gitattributes` and the response. Pass when all of these hold; list every
criterion that fails.

1. The answer explains that `spotfire ahead` means someone saved a change to the function in
   Spotfire since the last sync, and that `dxp push --force` would overwrite it.
2. It advises against forcing without review: run `dxp pull` (or `dxp push --dry-run` / `pull
   --dry-run` to see the Spotfire-side diff), review the change with the person who made it,
   merge both changes in the source file, then apply and commit, including `dxpkit.lock`.
3. It warns that a script written by `dxp push` keeps the old trust approval, so the function
   opens untrusted and will not run until someone trusts it in Analyst (File > Manage trust >
   Review > Trust, refresh, save), or recommends applying through the Spotfire API with the
   update tool so it runs for the demo.
4. `.gitattributes` contains `*.dxp diff=dxp`, and the commands include
   `git config diff.dxp.textconv "dxp textconv"` (or the standard-library `dxp_inventory.py text`
   driver), with a note that every clone runs the config once.
5. It states that textconv applies to local `git diff` and `git log`/`git show`, and that the
   GitHub web view of a pull request still shows the DXP as binary, suggesting a workaround (the
   diff in the PR description, or committed extracted text).
6. It treats dxpkit as a prerequisite installed from its own source, and does not suggest
   copying dxpkit code into the repository.
7. It does not claim that Git can merge two DXP files.
