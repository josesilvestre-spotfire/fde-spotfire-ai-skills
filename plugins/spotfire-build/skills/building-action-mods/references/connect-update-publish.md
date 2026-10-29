# Connect, update and publish an action mod

Spotfire Analyst 15.0. Dialog labels can differ slightly between versions.

## Make the mod available in an analysis

1. Tools > Development > Mods development. Then either:
   - **Connect to file** (installed client): pick the project's `mod-manifest.json`.
   - **Development server**: in the project folder run
     `npx @spotfire/mods-dev-server . --allow-project-root true` (Node 22.12 or later; use
     `npx.cmd` if PowerShell blocks `npx.ps1`), then Connect to development server on port 8090.
2. The mod appears under In development with its scripts.
3. **Disconnect.** Spotfire copies the files into the analysis, embeds the mod and signs it with
   your code-trust certificate. If Disconnect is not offered after Connect to file, use the
   development server.
4. Save the analysis.

If Spotfire says it cannot sign or trust the mod, your account has no code-trust certificate on
the server you are logged in to: ask the Spotfire administrator.

Through the API, a script can find mods that are embedded, installed or pinned with
`Document.ModManager.GetActionModsIncludingPinned()` (15.0). Loading a mod from a folder or a
`.mod` file has no public API.

## Update an embedded mod

1. Edit the scripts (and the manifest if needed) and raise `version`. Never change script ids or
   parameter names: hosts are bound to them.
2. Run the checks (type check, scenarios, `scripts/check_action_mod.py`).
3. Open the analysis, connect the project again and accept replacing the embedded mod with the
   same id. After a manifest change, Reload manifest.
4. Disconnect (embeds and signs again), save.

## Publish for other users

- Save the mod as a library item (from the Mods development panel), for example under the app's
  library folder, and pin it so it appears in the Actions flyout for you or, pinned by an
  administrator, for everyone.
- An analysis that uses the library mod refers to the library item instead of a local folder, and
  library updates reach every analysis that uses it. A mod connected from a folder stores the
  folder path in the DXP: fine for development, not for a customer package.
- Other users get a trust prompt for your signature the first time one of its actions runs, unless
  an administrator trusts the signer. To trust a mod across environments without prompts, sign it
  with Spotfire Package Builder (Spotfire Developer SDK) and a CA certificate, or have the
  administrator deploy the certificate.

The development server, Disconnect and save route is how the action mod of a published analysis
was embedded (the mod's origin in that DXP records the upload from a local development server).
The library, pinning and Package Builder steps are **Not yet tested** with this library.
