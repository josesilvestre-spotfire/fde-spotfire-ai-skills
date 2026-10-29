---
max_turns: 12
allowed_tools: [Read, Glob, Grep, Skill, Write, Bash]
---

We run Spotfire Analyst 15.0 with its bundled Python, and IT will not let us install any
packages into it. We want an LSTM autoencoder that flags anomalies across 8 compressor tags
sampled hourly.

Write the Python data function script as `detector.py`. It receives a table with a
`Timestamp` column, the 8 tag columns, a `Split` column (`train` or `test`) and a `Label`
column (`Normal` or an event name). It should train on the training rows labelled Normal,
score every row, and output a scores table plus the alarm threshold as a single value for a
document property.

Also tell me how we should evaluate the detector before we show its flags to operations.
