"""Build a browser preview of text-area HTML with the app stylesheet.

The preview puts each HTML file in a frame the width of a text area, swaps
every {{control:<id>}} placeholder for a stand-in with the markup Spotfire
renders for that control (buttons are input.sfc-action-button, drop-downs
div.sf-element-dropdown, and so on), and runs the injector script exactly
as Spotfire would: after the HTML, with the host's #style-container in the
page. Open the file in any browser to review the look before you touch
Spotfire. Stand-ins approximate Spotfire's own widgets; drop-downs, list
boxes and sliders look simpler than in Analyst.

Control kinds come from --controls (a JSON object {id: {"kind", "label"}},
the same shape as the controls of a text area in a build spec), else from
the id: run*, reset*, save*, open*, apply*, clear*, delete*, export* are
buttons; kpi*, legend*, status*, *Message, *Label are labels; select*,
pick* are drop-downs; slider* are sliders; list* are list boxes; input*
are text boxes.

Usage:
  python make_preview.py FILE_OR_FOLDER [...] [--script "Apply App Styles.js"]
                         [--controls controls.json] [--width 900]
                         [--out preview.html]
  python make_preview.py --self-test
"""

import argparse
import html
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCRIPT = os.path.join(HERE, "..", "assets", "Apply App Styles.js")
HOST_START = '<div id="style-container"></div><div id="styleDivSF"></div>'
PLACEHOLDER = re.compile(r"\{\{control:([A-Za-z][A-Za-z0-9]*)\}\}")
BUTTON_WORDS = ("run", "reset", "save", "open", "apply", "clear", "delete",
                "export", "go", "show", "refresh")
SAMPLE_VALUES = ["61.8", "3", "21,400", "1,284", "208", "0"]


def words(identifier):
    """camelCase id -> Title Case words without the kind prefix."""
    parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", identifier)
    if parts and parts[0].lower() in ("input", "select", "pick", "slider",
                                      "list", "kpi", "legend", "label"):
        parts = parts[1:] or parts
    return " ".join(p[:1].upper() + p[1:] for p in parts)


def guess_kind(identifier):
    low = identifier.lower()
    if low.startswith(BUTTON_WORDS) or "button" in low or "btn" in low:
        return "button"
    if low.startswith(("kpi", "legend", "status", "label")) or \
            low.endswith(("message", "label", "text")):
        return "label"
    if low.startswith(("select", "pick", "dropdown")):
        return "dropdown"
    if low.startswith("slider"):
        return "slider"
    if low.startswith("list"):
        return "listbox"
    if low.startswith("input"):
        return "input"
    return "label"


def stand_in(identifier, spec, index):
    kind = spec.get("kind") or guess_kind(identifier)
    label = html.escape(spec.get("label") or words(identifier))
    if kind == "button":
        return ('<input type="button" class="sfc-action-button" value="%s" />'
                % label)
    if kind in ("input", "multilineInput"):
        return ('<input type="text" class="sfc-text-box property text-box" '
                'value="65" />')
    if kind in ("dropdown", "checkbox"):
        return ('<div class="sf-element-dropdown" style="display: '
                'inline-block; min-width: 140px; padding: 1px 6px; border: '
                '1px solid #C8CCD2">%s v</div>' % ("Yes" if kind == "checkbox"
                                                  else "Pump A"))
    if kind == "slider":
        return ('<span class="TextAreaSlider"><span class="sf-element-range" '
                'style="display: inline-block; width: 140px; height: 4px; '
                'background: #D0D5DD; vertical-align: middle"></span> '
                '<span class="ValueLabel">24</span></span>')
    if kind in ("listbox", "multiSelectListbox", "radio"):
        return ('<div class="sf-element-list-box"><div class="sf-element-'
                'list-box-item sfpc-selected">Pump A</div><div class="sf-'
                'element-list-box-item">Pump B</div></div>')
    if kind == "link":
        return '<a href="javascript:void(0);">%s</a>' % label
    return "<span>%s</span>" % SAMPLE_VALUES[index % len(SAMPLE_VALUES)]


def fill(text, controls):
    counter = [0]

    def replace(match):
        counter[0] += 1
        identifier = match.group(1)
        return stand_in(identifier, controls.get(identifier, {}), counter[0])
    return PLACEHOLDER.sub(replace, text)


def iter_files(paths):
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.lower().endswith((".html", ".htm")):
                    yield os.path.join(path, name)
        else:
            yield path


def build(paths, script_path, controls, width):
    items = []
    for path in iter_files(paths):
        with open(path, encoding="utf-8") as f:
            items.append((os.path.basename(path), f.read()))
    items.sort(key=lambda item: not item[1].lstrip().startswith(HOST_START))
    with open(script_path, encoding="utf-8") as f:
        script = f.read()
    frames = []
    if not items or not items[0][1].lstrip().startswith(HOST_START):
        frames.append(HOST_START)
    for name, text in items:
        frames.append('<div class="preview-name">%s</div>\n<div class="'
                      'preview-frame" style="width: %dpx">\n%s\n</div>'
                      % (html.escape(name), width, fill(text, controls)))
    return ("<!DOCTYPE html>\n<html>\n<head>\n<meta charset=\"utf-8\" />\n"
            "<title>Text area preview</title>\n<style>\n"
            "body { margin: 16px; background: #FAFAF8; }\n"
            ".preview-name { margin: 12px 0 4px 0; font: 11px Consolas, "
            "monospace; color: #5B6370; }\n"
            ".preview-frame { padding: 6px; border: 1px solid #DCDFE4; "
            "background: #FFFFFF; }\n</style>\n</head>\n<body>\n"
            + "\n".join(frames) + "\n<script>\n" + script
            + "\n</script>\n</body>\n</html>\n")


def self_test():
    assert words("runAnalysis") == "Run Analysis"
    assert words("kpiFleetEfficiency") == "Fleet Efficiency"
    assert guess_kind("runAnalysis") == "button"
    assert guess_kind("kpiFlowRate") == "label"
    assert guess_kind("selectPump") == "dropdown"
    assert guess_kind("sliderMinPoints") == "slider"
    assert guess_kind("statusMessage") == "label"
    snippets = os.path.join(HERE, "..", "assets", "snippets")
    page = build([snippets], DEFAULT_SCRIPT,
                 {"openDetail": {"kind": "link", "label": "Pump detail"}}, 900)
    assert "{{control:" not in page
    assert page.split("<script>")[0].count('id="style-container"') == 1
    assert 'class="sfc-action-button" value="Run Analysis"' in page
    assert '<a href="javascript:void(0);">Pump detail</a>' in page
    with tempfile.TemporaryDirectory() as folder:
        path = os.path.join(folder, "plain.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write('<div class="app-ta">{{control:kpiValue}}</div>')
        page = build([path], DEFAULT_SCRIPT, {}, 400)
        assert page.split("<script>")[0].count('id="style-container"') == 1
    print("self-test passed")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--script", default=DEFAULT_SCRIPT)
    parser.add_argument("--controls")
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--out", default="preview.html")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.paths:
        parser.error("give HTML files or folders")
    controls = {}
    if args.controls:
        with open(args.controls, encoding="utf-8") as f:
            controls = json.load(f)
    page = build(args.paths, args.script, controls, args.width)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(page)
    print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
