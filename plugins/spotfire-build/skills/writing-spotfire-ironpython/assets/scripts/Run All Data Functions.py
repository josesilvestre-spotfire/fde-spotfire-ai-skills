# Run All Data Functions
# Runs the analysis's data functions in dependency order: the generator
# first, then the functions that read its tables, then the joins. Each one
# finishes before the next starts, so a later function sees the tables an
# earlier one wrote. Attach it to a button such as RUN ALL.
# A new data function is done when it is in its file, in ORDER below and in
# the setup guide.

ORDER = [
    "Generate Pump Readings",
    "Calculate Pump Efficiency",
    "Rank Pumps",
]

functions = {}
for function in Document.Data.DataFunctions:
    functions[function.Name] = function

ran, missing, stale = [], [], []
for name in ORDER:
    if name not in functions:
        missing.append(name)
        continue
    function = functions[name]
    # ExecuteSynchronously runs the function now; Execute() would only queue
    # it until this script ends. It never raises. NeedsRefresh is expected to
    # stay True after a failed or untrusted run (not yet tested live), so the
    # status property each function writes is the safer check.
    function.ExecuteSynchronously()
    if function.NeedsRefresh:
        stale.append(name)
    else:
        ran.append(name)

message = "Ran %d of %d data functions" % (len(ran), len(ORDER))
if stale:
    message += "; may not have finished (see notifications and trust): " + ", ".join(stale)
if missing:
    message += "; not found: " + ", ".join(missing)
Document.Properties["StatusMessage"] = message
