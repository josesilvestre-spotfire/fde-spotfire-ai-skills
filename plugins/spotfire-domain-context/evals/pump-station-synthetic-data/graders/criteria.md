---
type: llm
weight: 1
---

Grade the response and `gen_pump_data.py` (and its output if present). Pass when at least 6
of the 8 criteria hold and criterion 3 holds.

1. **Physics, not curve fitting.** Tags are derived from shared drivers through physics: a
   pump head curve (head falling with flow), line friction scaling with flow to a power
   between about 1.75 and 2, discharge pressure from suction plus head, motor power from
   flow, head and efficiency, crude temperature following ambient with a lag.
2. **Operations.** Rate follows an operating state machine with irregular setpoint holds
   (no fixed period), ramps, and at least one trip or shutdown that all tags respond to
   coherently.
3. **Coloured noise.** Noise is autocorrelated (Ornstein-Uhlenbeck, AR(1) or equivalent),
   not independent white noise added per sample, and tags correlate through shared drivers
   rather than an injected correlation matrix.
4. **Event contract.** Events come from a registered catalog with more than one family (for
   example process, mechanical, instrumentation, electrical), and each event type has an
   expected signature (tag directions and magnitudes) that the script checks after
   generation.
5. **Instrument faults.** At least one event type is an instrument fault (frozen value,
   drift or noise burst), distinct from process events.
6. **Train and holdout.** A split column marks a training period and a later holdout period,
   each with its own events, and an event id column is stamped onto the time series rows so
   series and events can be related in Spotfire.
7. **Ran and checked.** The script was run, and the response reports concrete validation
   results (event signature checks, absence of an artificial daily rhythm, autocorrelation,
   value ranges) rather than only describing the intent.
8. **Honest constants.** Seeded and reproducible, and the response or code marks its
   constants as illustrative or cites them, rather than presenting them as real plant values.
