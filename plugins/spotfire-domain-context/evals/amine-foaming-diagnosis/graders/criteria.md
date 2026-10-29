---
type: llm
weight: 1
---

Grade the response and the file `foaming_mode.yaml`. Pass when at least 6 of the 8 criteria
hold and criteria 1 and 2 both hold.

1. **Diagnosis.** Names contactor foaming as the most likely explanation, citing the fast dP
   rise, the treated gas H2S increase, the level instability and the amine loss together at
   a flat gas rate.
2. **Root cause clue.** Points out that the lean amine (95 F) is colder than the inlet gas
   (100 F), so hydrocarbons can condense in the contactor and cause foaming, and that lean
   amine is normally kept warmer than the inlet gas.
3. **Confounders against differentials.** Separates benign explanations (a gas rate change,
   which the flat rate argues against; a dP transmitter fault) from competing faults
   (flooding from over-circulation, tray damage, solids or chemical carryover), or otherwise
   makes clear that the two lead to different actions.
4. **Operator checks.** Gives concrete field checks: a foam test on a solution sample and
   antifoam injection, the lean amine cooler and its temperature control, inlet separator or
   filter performance and carryover, hydrocarbons in the flash tank, a second dP indication.
5. **Onset and signature.** The YAML gives `onset` as hours (or equivalent), and a
   `signature` that maps two or more measurement roles to directions (for example contactor
   dP up sharply, treated gas H2S up, makeup up, level erratic).
6. **Card structure.** `foaming_mode.yaml` exists and is valid YAML with `confounders` and
   `differentials` as separate lists, plus `discriminators`, field checks and a `source`.
7. **Honest sourcing.** Rules of thumb (for example the lean amine approach to inlet gas) and
   any spec values are marked as typical, unverified or contract-driven rather than stated as
   facts about this unit; the treated gas H2S spec is not asserted from memory.
8. **No overreach.** Presents the diagnosis as the leading hypothesis to confirm in the
   field, not as an established fact.
