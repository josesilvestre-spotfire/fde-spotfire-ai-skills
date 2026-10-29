---
type: llm
weight: 1
---
Grade the App Brief the assistant wrote (the file `workspace/apps/CompressorTripReview/app-brief.md`,
or the full brief in its reply if no file was written).

Pass when all of these hold:

1. The brief follows the App Brief template: a title `# App Brief: <name>`, a `Status: draft` line
   and the sections Business problem, Users, Decisions the app supports, KPIs, Inputs, Outputs,
   Data sources, Refresh cadence, Out of scope and Open questions, in that order.
2. The first sentence of "Business problem" names who has the problem (reliability engineers,
   control room, the plants) and the problem itself (unplanned compressor trips found only after
   they happen). It does not contain "anomaly detection", "machine learning", "AI", "Spotfire" or
   "dashboard".
3. The business problem states the cost with the user's numbers (8 trips a year, about 12 hours of
   reduced throughput each) and how it is handled today (data pulled from the historian after a
   trip).
4. The app name describes the business problem (for example compressor trips or compressor
   reliability), not the technique.
5. Every KPI row has a Logic Spec ID (L01, L02, ...), a unit, a threshold or target and a page. The
   assistant either wrote `logic-spec.md` with matching entries marked `Status: inferred`, or
   explicitly listed the reserved IDs as inferred entries to be completed.
6. The alert limits per compressor appear as an input set by the reliability engineers, with a
   type, default and range.
7. The simulator's random seed, noise level and injected faults are inputs marked for advanced
   users or a Data Generation page, separate from the operator inputs.
8. The open question about Web Player versus Analyst is recorded, and assumptions the assistant
   made (thresholds, units, defaults, costs per hour) are marked as assumptions or open questions
   instead of stated as facts. At least one question is marked Blocking, or the reply explains why
   none blocks the build.
9. "Out of scope" lists at least one concrete item.
10. Data sources give the historian's grain (hourly per compressor) and approximate rows or asset
    count, and the brief says which columns users must supply when they bring their own data.

Fail when the brief opens with the technique or with Spotfire features, when pages or visuals are
proposed before the business problem is stated, or when invented facts (customer names, costs not
given and not marked as assumptions) appear as confirmed.
