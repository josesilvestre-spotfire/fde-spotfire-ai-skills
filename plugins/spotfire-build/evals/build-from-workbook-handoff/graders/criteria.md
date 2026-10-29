---
type: llm
weight: 1
---

Grade the response and `apps/line-pressure-profile/BUILD-PLAN.md`. The app folder may be missing in
the test sandbox; then grade the plan and the response on what they say they would do. Pass when all
of these hold; list every criterion that fails.

1. The plan starts by reading `app-brief.md` and `logic-spec.md` and checks the App Brief's open
   questions: a question marked Blocking stops the build until the owner answers it.
2. It validates the draft `spec.json` with `dxpgen.py validate` before changing it.
3. It handles the CSV sources correctly: either converts `data/*.csv` to SBDF with `sbdf_export.py`
   run by Spotfire's own Python and switches the table sources to `sbdf` for the standard engine, or
   builds with `--tier slim`, and says why (the standard engine loads SBDF tables only).
4. It keeps `datafunctions/calculate_pressure_profile.py` unchanged as the data function code,
   because it is the model the ingest skill reconciled against the workbook (from
   `ingest/calc_model.py`); any change goes back through the ingest skill with a new reconciliation.
5. It says the user is told before `app-brief.md` or `logic-spec.md` changes, and does not rewrite
   them on its own.
6. The build steps are the skill's: `dxpgen.py build`, run the builder (unattended through the
   `running-spotfire-unattended` skill, or pasted into Analyst with "Execute in transaction"
   unticked and the dialog closed with Cancel), open the saved DXP, then `verify_dxp.py check`.
7. It lists the manual steps: the text-area input and label controls of the draft become markers
   and entries in `build/MANUAL-STEPS-<tier>.md`, added by hand in Analyst; the `app.theme` is a
   manual step too.
8. The reconciliation is planned after the build: export the DXP's output tables to CSV (the
   skill's `export_tables_job.py` through the unattended runner, or File > Export in Analyst), then
   run the reconciliation step of the `ingesting-excel-workbooks` skill (the app folder's
   `ingest/reconcile.py compare` against `ingest/expected.csv`) for the stored inputs and every
   case, with the Logic Spec's tolerance; every output must match or be explained.
9. It refers to other skills by name (for example `ingesting-excel-workbooks`,
   `running-spotfire-unattended`), never by a path into another skill's folder.
10. Nothing in the plan hand-edits `AnalysisDocument.xml` or relies on non-public Spotfire API.
