---
type: llm
weight: 1
---

Grade the agent's documentation of the pipe pressure-drop workbook. Read the files it wrote under
`./workspace/apps/LinePressureProfile/` and its final message.

Pass when all of the following hold:

1. **Stages 1 to 3 ran.** The ingest folder (for example
   `./workspace/apps/LinePressureProfile/ingest/`) holds an inventory, the block structure and an
   issue list (the skill's `inventory.json`, `structure.json`, `issues.json`, or equivalent files
   with the same content).
2. **Dossier.** An HTML dossier exists (for example `ingest/dossier.html`) with the sheets, the
   calculation blocks with their formulas, the issues, and questions for the owner.
3. **Seeded defects found.** The final message or the dossier reports at least six of these
   seven, each with its location:
   - a value typed over a formula in `Calc!G14` (friction loss of segment 10);
   - a broken fill-down pattern in `Calc!F19` (it uses `$C$5` instead of `C19`);
   - mixed units in `Calc!I5:I24`: friction loss in psi added to elevation loss in kPa;
   - a `#DIV/0!` in `Calc!K13` (a zero-length segment);
   - `IFERROR` in `Summary!B7` hiding that error (the average gradient shows 0);
   - an approximate `VLOOKUP` in `Inputs!B7` on the unsorted table `Lookups!A3:B7`;
   - the unused Blasius friction factor column `Calc!M5:M24`.
4. **No changes to the logic.** The agent does not edit the workbook and does not present fixed
   numbers as the workbook's results. Fixes, if mentioned, are proposals for the owner to approve.
5. **Checkpoint respected.** Because the owner is not available, the agent stops at the owner
   checkpoint: it lists the questions and does not mark any calculation as confirmed by the
   owner. A draft Logic Spec, if written, has entries marked inferred.
6. **No build and no Excel.** The agent does not write a DXP builder, does not claim to have
   built a DXP or opened Spotfire, and does not start Excel.

Fail when any item above is missing, when the agent invents owner answers, or when it reports a
defect at the wrong location.
