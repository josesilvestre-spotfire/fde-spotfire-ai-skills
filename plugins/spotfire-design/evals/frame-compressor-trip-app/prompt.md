---
max_turns: 10
allowed_tools: [Read, Glob, Grep, Skill, Write]
---
Our reliability group wants "an anomaly detection app in Spotfire" for the gas compressors at our
three plants. Please write the App Brief so we can start the build.

What I know so far:

- Reliability engineers look at the compressors once a week; control room supervisors would check
  it at the start of every shift.
- We had 8 unplanned compressor trips last year. Each one cut plant throughput for about 12 hours.
  Right now an engineer only pulls vibration and discharge temperature data from the historian
  after a trip, to find out what happened.
- The historian has hourly data per compressor: vibration, discharge temperature, suction and
  discharge pressure, motor current. About 30 compressors in total.
- The engineers want to set their own alert limits per compressor.
- For the demo we will generate data with a simulator that has a random seed, a noise level and a
  list of injected faults.
- I don't know yet whether the control room uses Web Player or Analyst.

Save it as `workspace/apps/CompressorTripReview/app-brief.md` (our DXP_WORKSPACE is `workspace`).
