"""spec textArea -> engine kind "text" (engine/builders/text.py).

An HTML file stays a file the builder reads at run time (APP "html", relative to HOME\\html, like
the first builders); inline HTML (a string starting with "<") is carried in the builder (APP
"htmlText"). Controls -> APP "controls", one visible marker per {{control:<id>}} (t3/_sections.py,
engine/features/controls.py); the controls themselves are manual steps. JavaScript -> APP "js"
(engine/features/textjs.py): a .js file stays a file the builder reads at run time, [name, path
relative to HOME] (name = the file stem); inline {"name", "code"} is carried, [name, None, code].
CSS needs the slim tier for now (in safe mode CSS goes in through a JavaScript anyway).
"""
import os

from . import _sections
from ._common import blank

KIND = "text"
SPEC_TYPES = ("textArea",)
STYLE_KEYS = ()
HANDLED = ("html", "css", "js", "controls")


def _home_rel(app_dir, value):
    full = os.path.normpath(os.path.join(app_dir, value.strip()))
    return os.path.relpath(full, app_dir).replace("/", "\\")


def convert(v, rv, path, ctx):
    if not blank(v.get("css")):
        ctx.unsupported(path + ".css", "text-area CSS (inject it with a text-area JavaScript)")
    app_dir = str(ctx.app_dir)
    raw = rv.get("html")
    if isinstance(raw, str) and raw.strip() and not raw.lstrip().startswith("<"):
        full = os.path.normpath(os.path.join(app_dir, raw.strip()))
        rel = os.path.relpath(full, os.path.join(app_dir, "html"))
        out = {"html": rel.replace("/", "\\")}
    else:
        out = {"htmlText": v.get("html") or ""}
    if not blank(v.get("controls")):
        out["controls"] = _sections.controls(v, path, ctx)
    scripts = []
    raw_js = rv.get("js") if isinstance(rv.get("js"), list) else []
    for n, item in enumerate(raw_js):
        if isinstance(item, str) and item.strip():
            scripts.append([os.path.splitext(os.path.basename(item.strip()))[0], _home_rel(app_dir, item)])
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            scripts.append([item["name"], None, str(item.get("code") or "")])
        else:
            ctx.unsupported("%s.js[%d]" % (path, n), "a JavaScript entry that is not a file path or "
                            "{name, code}")
    if scripts:
        out["js"] = scripts                                  # engine feature textjs
    return out
