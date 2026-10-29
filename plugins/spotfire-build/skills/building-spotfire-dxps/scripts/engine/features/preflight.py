# Standard engine, feature part "preflight": an older builder pasted
# after the app folder changed must stop before it changes anything (the
# files it expects may be gone, and it would save a broken DXP over a
# good one). Included in every builder of an app that uses any feature
# (apps without features keep their builders byte-identical).
#   - missing_files(): the files this builder reads from HOME (APP
#     "files", listed by dxpgen when it generated the builder: sbdf
#     tables, data-function code, IronPython scripts, each visualization
#     mod's mod-manifest.json with the built files it lists, text-area
#     HTML and JavaScript) that are not there. The build calls it right
#     after the opened-from check, before the first document change, and
#     stops with mismatch_text() when anything is missing: nothing is
#     changed or saved, so the DXP of the matching version stays
#     untouched.
#   - log_stamp(head): the first log line names the release (dxpgen
#     release) and the spec.json hash the builder was generated from, so
#     a build log always says which spec built the DXP next to it.
# APP keys it reads: spec (first 12 hex digits of spec.json's sha256),
# release (only in builders of dxpgen release), files [path relative to
# HOME, ...]. Uses HOME (the builder literal). System.IO only, no
# Spotfire members.
from System.IO import File, Path

# ------------------------------------------------------------ preflight
PREFLIGHT_SHOWN = 4     # missing files named in the stop message


def missing_files():
    """APP files (relative to HOME) that do not exist."""
    return [rel for rel in APP["files"]
            if not File.Exists(Path.Combine(HOME, rel))]


def mismatch_text(missing):
    names = ", ".join(missing[:PREFLIGHT_SHOWN])
    if len(missing) > PREFLIGHT_SHOWN:
        names += " (and " + str(len(missing) - PREFLIGHT_SHOWN) + " more)"
    return ("This builder does not match the files in " + HOME
            + ": missing " + names + ". Use the builder that belongs to "
            "this version (see versions\\README.md). Nothing was changed.")


def log_stamp(head):
    """'[<release>, spec <hash>] ' + the log's head line."""
    tag = "spec " + APP["spec"]
    if APP.get("release"):
        tag = APP["release"] + ", " + tag
    return "[" + tag + "] " + head
