---
type: llm
weight: 1
---
Grade the assistant's answer.

Pass when all of these hold:

1. It tells the user to generate an API index from their own install with the library's
   `dump_api.ps1` (run through `powershell.exe`), passing the install folder with `-SpotfireHome`
   or the `SPOTFIRE_HOME` variable, and says the index is written to `$DXP_WORKSPACE\api` (or an
   `-OutDir` the user chooses).
2. It says the generator reads the assemblies by static reflection and does not start Spotfire, or
   otherwise makes clear it is safe to run next to an open Analyst.
3. It gives `sfapi.py` commands that check the script's members, including `has ... --set` for the
   members the script assigns, and `chain` (or `has` with an expression) for a path such as
   `Document.ActivePageReference.Visuals` or `LineChart.XAxis.Expression`.
4. It warns that `DataProperty.Description` has no setter on Spotfire 15.0, so the description must
   be given when the property is created (or shows that `has DataProperty.Description --set` will
   report the member as not settable).
5. It does not claim that an index ships with the library, and it suggests keeping the generated
   index out of shared repositories or version control.
6. It does not recommend non-public Spotfire classes, reflection into internal members, or
   decompiling Spotfire as the way to check members.

Fail when the commands or file names are invented (for example a different script name or an
index that is downloaded from the internet), or when the answer only says to "check the API
documentation" without the local index steps.
