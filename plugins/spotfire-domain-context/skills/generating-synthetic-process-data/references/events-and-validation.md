# Events and validation

## Event catalog

Every subtype the scheduler can emit is registered with its family and duration range:

```python
EVENT_CATALOG = {
    "Partial Restriction - High Line Pressure Drop": {"family": "Process", "days": (1, 3)},
    "Transmitter Freeze - Flat Discharge Pressure": {"family": "Instrumentation", "days": (1, 2)},
    "Power Loss Trip - Station Shutdown": {"family": "Electrical", "days": (0.2, 0.5)},
}
```

- **Families**: Mechanical, Process, Electrical, Instrumentation, Operational.
- **Names state the measurable effect**, then the cause: "High Discharge Temperature -
  Cooler Fouling", "Tower Flooding - High Differential Pressure", "Low Suction Pressure -
  Upstream Slugging".
- **Instrumentation events** are freeze (the value holds), drift (a slow bias walk) and
  noise bursts. They exist so detectors learn that a sensor fault is not a process fault.
- **Trip-class events** (emergency shutdown, power loss, planned maintenance, turnaround)
  feed the operations state machine, so every tag responds, including temperatures decaying
  toward ambient.
- **Onset dynamics and production impact differ by subtype**: a trip is a step, fouling is
  a ramp over weeks, a freeze is a flat line.
- A scheduler that emits a subtype missing from the catalog must raise. A turnaround subtype
  once reached the scheduler without registration; the KeyError is what caught it.

## VERIFY: the expected signature

```python
VERIFY = {
    "Partial Restriction - High Line Pressure Drop": {
        "line_dp_psi": ("up", 3.0, 25.0), "flow_bpd": ("down", 0.5, 15.0)},
    "Transmitter Freeze - Flat Discharge Pressure": {
        "discharge_psig": ("flat", 0.0, 0.0)},
}
```

Each entry is (direction, minimum, maximum) percent change of the event-window mean against
a pre-event baseline. Process upsets in earlier simulators were sized at about 3 to 12
percent of the tag mean (a design choice: big enough to detect, small enough to be
realistic). The harness asserts every generated event, so a physics change that silently
breaks a signature fails the build.

Keep the baseline clean: hold setpoint changes out of each event window and the few days
before it, and space events further apart than the baseline length.

## Validation suite

| Check | Pass condition | Why |
|---|---|---|
| Direction and magnitude | Every event meets its VERIFY entry | The labels are only useful if the data carries the signature |
| Spectral | No peak at one cycle per day on process tags after removing operating moves | A clock-driven rhythm on pumped flow is the most common synthetic giveaway |
| Thermal decay | Temperatures approach ambient during outages and recover with lag | Instant recovery is physically impossible |
| Monotonicity | Every curve family is monotonic where physics says it is | Catches per-point correction bugs such as the HI 9.6.7 B-parameter cliff |
| Realism statistics | Trip crash and recovery times, setpoint hold distribution, steady-state rate variability are reported | A reviewer compares them with plant experience |

The skeleton measures the spectral check as the ratio of power density in the 24-hour band
to the neighbouring bands, limit 3 (an illustrative choice). Coloured noise gives a ratio
near 1 whatever its correlation time; an added sine gives a peak, and a negative-control
test confirms the check catches one. An earlier build used "24-hour band below 3 percent of
variance" instead; that figure depends on how much low-frequency variance remains after
detrending, so treat it as UNVERIFIED.

## Realism targets for a new engine

Design choices from earlier simulators, not sourced plant values (UNVERIFIED):

- Setpoints held 6 to 30 days, aperiodic.
- Asymmetric ramps: trips fall within minutes, restarts take hours.
- Turnarounds every 12 to 20 months in a multi-year horizon (real turnaround intervals vary
  widely by unit; set them from the domain).
- Tank draws every 5 to 12 days.
- Process upsets 3 to 12 percent of tag mean.
- Instrumentation freeze, drift and noise-burst events present.
- Coloured noise on every tag.

## Train and holdout

- `Split` column with `train` and `test`; the holdout is the future, never a random sample
  of rows.
- Each split has its own events. Defaults that worked: about 150 training days with about 5
  events of 1 to 3 days (about 5 percent anomalous time), about 45 holdout days.
- Report detection performance on the holdout only, counted per event rather than per
  sample.
