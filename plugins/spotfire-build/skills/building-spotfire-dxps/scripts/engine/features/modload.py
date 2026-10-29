# Standard engine, feature part "modload": finds each visualization mod
# a visual uses (feature vizMods; builders/mod.py adds the visuals).
# The public API cannot add a mod to an analysis from a project folder
# or a .mod file, so the mod must already be listed by
# ModManager.GetVisualizationModsIncludingPinned() (public, 14.5): a mod
# embedded in the analysis the builder runs in, or a mod installed or
# pinned in your library. load_viz takes the listed mod with the
# version of the project's mod-manifest.json (APP vizMods third
# element), else a listed mod of another version with a NOTE line.
# Nothing listed: FAILED + TODO (VIZ_FIX); builders/mod.py then puts a
# placeholder text area where each of its visuals goes, and the build
# goes on.
# To make a mod available before you run the builder, use either route:
#   - pin or install the mod in your library, or
#   - in the new analysis with starter data, add the mod once (Tools >
#     Development > Mods development > Connect to file > its
#     mod-manifest.json, or drag its .mod file onto the page), keep the
#     visual it adds on the starter page, then run the builder there
#     (an app with mod visuals removes the starter pages only after its
#     own visuals exist). **Not yet tested** as a builder route.
# APP "vizMods": [[id, project folder relative to HOME, manifest
# version], ...] (only the mods a visual uses; the version is left out
# when the manifest has none).
# Uses LOG.
# @api Document.ModManager; ModIdentifier.Id; ModIdentifier.Version
# @api ModManager.GetVisualizationModsIncludingPinned

# --------------------------------------------------- visualization mods
VIZ = {}             # visualization mod id -> ModIdentifier
VIZ_FIX = ("make the mod available before the build: pin or install it "
           "in your library, or add it once to the starter page of a new "
           "analysis with starter data (Tools > Development > Mods "
           "development > Connect to file, or drag its .mod file onto "
           "the page) and run the builder there")


def viz_listed(mod_id):
    """The embedded, installed or pinned visualization mod with this id
    (embedded ones are listed first), or None."""
    for mid in Document.ModManager.GetVisualizationModsIncludingPinned():
        if mid.Id == mod_id:
            return mid
    return None


def load_viz(entry):
    """[id, project, manifest version]: a listed mod of that version,
    else a listed mod of another version (NOTE line)."""
    mod_id = entry[0]
    want = entry[2] if len(entry) > 2 else None
    listed = viz_listed(mod_id)
    if listed is None:
        raise Exception("the mod is not embedded, installed or pinned")
    VIZ[mod_id] = listed
    if want is not None and str(listed.Version) != want:
        LOG.append("NOTE viz mod " + mod_id + ": using version "
                   + str(listed.Version) + " instead of " + str(want)
                   + " (the version in the project's manifest)")
        return True
    LOG.append("OK viz mod " + mod_id + " " + str(listed.Version)
               + " (embedded or pinned)")
    return True
