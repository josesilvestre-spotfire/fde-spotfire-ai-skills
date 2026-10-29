# Script trust

Spotfire runs a data function, IronPython script or JavaScript only when it is trusted for the
user who opens the analysis. Every change that reaches a DXP has to account for this. The facts
below were proven on Spotfire Analyst 15.0, except where a line says it comes from the Spotfire
documentation.

## How approval is recorded

- Each data function and script in a DXP carries an approval stamp tied to the Windows account
  that approved it. Other accounts see the function as untrusted until they trust it.
- A script set through the Spotfire API in the user's own Analyst session is approved for that
  user and runs at once. The update tool in this skill relies on this: the unattended Analyst
  session runs under your account, so the function it changes is approved for you.

## What a byte replacement does

- `dxp push` (dxpkit) and any other tool that rewrites the script inside the DXP file without
  Spotfire keep the old approval stamp. The stamp no longer matches the script, so the function
  opens as untrusted ("not trusted and could not be executed").
- Running such a function through the API (`ExecuteSynchronously()`) silently does nothing: no
  error, and the output tables keep their old rows.
- A diff of the two DXP files shows the script change but no stamp change. A change made in
  Spotfire or applied through the API shows a new stamp as well.
- Trusting the pushed function in Analyst and saving did not change the stamp digest that a
  diff shows, so a diff cannot tell whether a function has been trusted since.

## Fixing an untrusted function

1. Open the analysis in Analyst.
2. **File > Manage trust**, select the function, **Review**, then **Trust**.
3. Refresh the function (or the data), then save.

After trust and save, the saved DXP runs unattended for that user. A copy saved before the
trust step stays untrusted.

## Other users

- The approval belongs to the account that applied or trusted the change. Every other user
  trusts the changed function in Analyst, or a member of the **Script Author** group trusts it
  for everyone (Spotfire documentation, Manage trust).
- Data functions cannot be signed (Spotfire documentation).
- Web clients cannot grant trust (Spotfire documentation). A function that is untrusted for a
  Web Player user stays untrusted until it is trusted in Analyst.

## Consequences for these skills

- Apply script changes through the Spotfire API (`update_data_function.py`), not by byte
  replacement, when the analysis must run right after the change.
- Use `dxp push` only when a person will open the analysis and trust the change, and say so in
  the pull request.
- A person reviews and approves every promotion. Trust in Analyst is part of that review, not
  something to automate away.
