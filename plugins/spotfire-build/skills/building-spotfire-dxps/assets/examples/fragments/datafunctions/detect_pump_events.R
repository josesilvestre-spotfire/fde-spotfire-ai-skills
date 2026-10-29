# ==============================================================================
#  Detect Pump Events  (v1.0)  - TERR data function
#  Rebuilds the PUMP_EVENTS table from over-current episodes in the marked
#  PUMP_DATA rows (assets/examples/fragments/datafunctions.json). An event is a run of
#  consecutive samples of one pump whose motor current exceeds
#  MotorCurrentLimit; samples before historyStart are ignored.
#  Severity: High when the peak current reaches 1.2 x the limit, else Medium.
#  Runtime: TERR base functions only.
# ------------------------------------------------------------------------------
# STAGING: INPUT PARAMETERS  (Data function properties > Input parameters)
# ------------------------------------------------------------------------------
#   name               type     document property     notes
#   pumpData           Table    (table PUMP_DATA)     all columns; limited by marking "Selected Pump"
#   MotorCurrentLimit  Value    MotorCurrentLimit     Real (A)
#   historyStart       Value    (constant 2026-01-01T00:00:00)   DateTime
# ------------------------------------------------------------------------------
# STAGING: OUTPUT PARAMETERS (Data function properties > Output parameters)
# ------------------------------------------------------------------------------
#   name               type     destination
#   PUMP_EVENTS        Table    replaces the data of table "PUMP_EVENTS"
# ------------------------------------------------------------------------------
#  PUMP_EVENTS - Event ID, Pump ID, Start, End, Severity, Description
#                (same columns as the loaded events table: event list / Gantt)
#  Refresh: manual (Data > Data function properties > Refresh), not run at build.
# ==============================================================================

# ============================== STAGING: INPUTS ==============================
if (!exists("pumpData")) {
  t0 <- as.POSIXct("2026-01-01 00:00:00", tz = "UTC")
  pumpData <- data.frame(
    "Timestamp" = rep(t0 + 3600 * (0:23), 2),
    "Pump ID" = rep(c("P-101", "P-102"), each = 24),
    "Motor Current (A)" = c(rep(95, 10), rep(131, 3), 150, rep(96, 10), rep(90, 24)),
    check.names = FALSE, stringsAsFactors = FALSE)
}
if (!exists("MotorCurrentLimit") || is.null(MotorCurrentLimit)) {
  MotorCurrentLimit <- 120
}
if (!exists("historyStart") || is.null(historyStart)) {
  historyStart <- as.POSIXct("2026-01-01 00:00:00", tz = "UTC")
}
MotorCurrentLimit <- as.numeric(MotorCurrentLimit)
# ============================================================================

samples <- data.frame(
  pump = as.character(pumpData[["Pump ID"]]),
  time = as.numeric(as.POSIXct(pumpData[["Timestamp"]])),
  current = as.numeric(pumpData[["Motor Current (A)"]]),
  stringsAsFactors = FALSE)
samples <- samples[!is.na(samples$time) & !is.na(samples$current) &
                     samples$time >= as.numeric(as.POSIXct(historyStart)), ]
samples <- samples[order(samples$pump, samples$time), ]

pumps <- character(0)
starts <- numeric(0)
ends <- numeric(0)
peaks <- numeric(0)
counts <- integer(0)
for (p in unique(samples$pump)) {
  s <- samples[samples$pump == p, ]
  runs <- rle(s$current > MotorCurrentLimit)
  last <- cumsum(runs$lengths)
  first <- last - runs$lengths + 1
  for (k in which(runs$values)) {
    seg <- s[first[k]:last[k], ]
    pumps <- c(pumps, p)
    starts <- c(starts, min(seg$time))
    ends <- c(ends, max(seg$time))
    peaks <- c(peaks, max(seg$current))
    counts <- c(counts, nrow(seg))
  }
}

# ============================== STAGING: OUTPUTS =============================
PUMP_EVENTS <- data.frame(
  "Event ID" = sprintf("DET-%04d", seq_along(pumps)),
  "Pump ID" = pumps,
  "Start" = as.POSIXct(starts, origin = "1970-01-01", tz = "UTC"),
  "End" = as.POSIXct(ends, origin = "1970-01-01", tz = "UTC"),
  "Severity" = as.character(ifelse(peaks >= 1.2 * MotorCurrentLimit, "High", "Medium")),
  "Description" = sprintf("Motor current above %.0f A for %d samples (peak %.1f A)",
                          rep(MotorCurrentLimit, length(pumps)), counts, peaks),
  check.names = FALSE, stringsAsFactors = FALSE)
# ============================================================================
