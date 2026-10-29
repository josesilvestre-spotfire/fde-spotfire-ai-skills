# Standard engine, feature part "controls": text-area controls.
# Spotfire 15.0 has no public API that adds a property control or an
# action control to a text area, so the builder does not create them.
# Each {{control:id}} placeholder in the HTML becomes a visible marker
# such as "[Drop-down list: SelectedPumpId]", and the build log and
# MANUAL-STEPS list how to insert each control by hand (Edit Text Area >
# Insert Property Control or Insert Action Control). A placeholder whose
# id the spec does not describe keeps a "[control: id]" marker.
# APP text visual "controls": {id: marker text}.
import re

# ------------------------------------------------- text-area controls
CTRL_RE = re.compile(r"\{\{\s*control\s*:\s*([^{}\s]+)\s*\}\}")


def control_marker(text):
    """A visible, sanitizer-safe marker (inline style, plain values)."""
    text = text.replace("&", "&amp;").replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return ('<span style="color: #B3261E; border: 1px dashed #B3261E; '
            'padding: 0 4px">[' + text + ']</span>')


def place_controls(v, vs, html):
    """Every {{control:id}} becomes the marker of its control."""
    def fill(m):
        cid = m.group(1)
        return control_marker(vs["controls"].get(cid, "control: " + cid))
    return CTRL_RE.sub(fill, html)
