# Meaning and the dossier

Stage 4 turns the structure into meaning: what each block computes, in which units, and why the
workbook exists. You write `ingest/meaning.json`, then `dossier.py` merges it into
`dossier.html` for the owner.

## Sources of meaning

1. Labels, headers and units next to each block (already in `structure.json`).
2. Cell comments and notes (`inventory.json`, sheets[].comments).
3. The formula itself: recognise known correlations (Darcy-Weisbach, Swamee-Jain, Arps decline,
   Hazen-Williams, ideal gas, discounting) and name them with a reference.
4. Chart titles, pivot names and the summary sheet: they show what the users look at.
5. The owner. Ask; never invent a goal, a user or a unit.

## Owner interview

Ask these before writing the goal and the decisions:

1. What question does this workbook answer, and who asks it?
2. Who changes which inputs, and how often?
3. Which numbers do people read, and what do they decide from them?
4. What do you do by hand around the workbook (paste data, copy results, run Goal Seek)?
5. Where does the input data come from, and how often does it change?
6. Which results have you checked against another source?

## meaning.json

```json
{
 "app": "Line Pressure Profile",
 "status": "draft for owner review",
 "goal": "One or two sentences.",
 "users": [{"role": "Pipeline engineer", "use": "Sets flow and fluid inputs, reads outlet pressure."}],
 "decisions": ["Can the line carry the planned flow rate?"],
 "manualSteps": ["Paste the segment survey into the Segments sheet."],
 "blocks": {
  "B016": {"name": "Velocity", "unit": "ft/s",
           "equation": "v = Q * 5.615 / 86400 / (pi * (D/12)^2 / 4)",
           "meaning": "Mean velocity from the volumetric flow rate.",
           "reference": "continuity equation", "logicId": "L02"},
  "Inputs!B3": {"name": "Flow rate", "unit": "bbl/d", "meaning": "Planned flow rate."}
 },
 "questions": [{"question": "Is the roughness table meant to be sorted?", "blocking": false,
                "about": "Lookups!A3:B7"}]
}
```

Keys of `blocks` are block IDs from `structure.json`, or `Sheet!Cell` for a single input cell.
`logicId` links the block to its Logic Spec entry.

## Writing the Logic Spec from the meaning

- One Logic Spec entry per calculation the outputs need; several blocks may form one entry
  (a first-row formula and its filled-down copy).
- "Source in the original work" names the workbook range, its exceptions and the issue IDs.
- Status is `inferred` until the owner confirms the entry at checkpoint 1.
- The equation describes what the workbook does now. A different intended equation goes into
  the change list, not into the entry.

## Checkpoint 1

Send `dossier.html` to the owner. The owner confirms the goal, the users and decisions, the
meaning of each block and answers the questions marked blocking. Record the answers in
`meaning.json` (`status`, `questions[].answer`) and the date in the App Brief's Status line.
Logic changes are not made at this checkpoint.
