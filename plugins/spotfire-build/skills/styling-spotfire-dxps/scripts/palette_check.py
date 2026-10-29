"""WCAG 2 contrast of the colors in the injector script and the palette.

Reads the THEME colors and the chip rules (background, border, text) from
the injector script and prints each color's contrast against the canvas and
against white, plus each chip's text against its background. Text needs
4.5:1 (3:1 for text of 18 px and larger, or 14 px bold); lines and markers
need 3:1 against the background they sit on.

Usage:
  python palette_check.py ["Apply App Styles.js"] [--canvas "#FAFAF8"]
  python palette_check.py --self-test
Exit code 1 when a THEME text color (ink, muted, accent) or a chip is
below 4.5:1 on its background.
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SCRIPT = os.path.join(HERE, "..", "assets", "Apply App Styles.js")
TEXT_COLORS = ("ink", "muted", "accent", "accentHover", "accentPressed",
               "success", "danger")
STATUS = [("Normal", "#2E9E5B"), ("Warning", "#F2C12E"), ("Alarm", "#F07C1F"),
          ("Critical", "#D93A2B"), ("Offline", "#A0A0A0")]


def luminance(hex_color):
    h = hex_color.lstrip("#")
    channels = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
              for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a, b):
    la, lb = sorted([luminance(a), luminance(b)], reverse=True)
    return (la + 0.05) / (lb + 0.05)


def read_palette(text):
    theme = dict(re.findall(r'(\w+):\s*"(#[0-9A-Fa-f]{6})"', text))
    chips = []
    for name, body in re.findall(r"\.(chip-[a-z]+) \{([^}]*)\}", text):
        colors = dict(re.findall(r"(background|border-color|color):\s*"
                                 r"(#[0-9A-Fa-f]{6})", body))
        if "background" in colors and "color" in colors:
            chips.append((name, colors["color"], colors["background"]))
    return theme, chips


def report(text, canvas):
    theme, chips = read_palette(text)
    failures = []
    print("color            hex      canvas  white")
    for name, value in sorted(theme.items()):
        on_canvas, on_white = contrast(value, canvas), contrast(value, "#FFFFFF")
        print("%-16s %s  %5.2f  %5.2f" % (name, value, on_canvas, on_white))
        if name in TEXT_COLORS and min(on_canvas, on_white) < 4.5:
            failures.append(name)
    print("\nstatus fills (markers, bars, chips; never thin text)")
    for name, value in STATUS:
        print("%-16s %s  %5.2f" % (name, value, contrast(value, canvas)))
    print("\nchip             text on background")
    for name, fg, bg in chips:
        ratio = contrast(fg, bg)
        print("%-16s %5.2f" % (name, ratio))
        if ratio < 4.5:
            failures.append(name)
    return failures


def self_test():
    assert abs(contrast("#000000", "#FFFFFF") - 21.0) < 1e-6
    assert abs(contrast("#FFFFFF", "#FFFFFF") - 1.0) < 1e-6
    sample = ('var THEME = { ink: "#1F2328", muted: "#999999" };\n'
              's + " .chip-normal { background: #E3F3E9; border-color: #93D1AC;'
              ' color: #1E6B3D; }",')
    theme, chips = read_palette(sample)
    assert theme == {"ink": "#1F2328", "muted": "#999999"}, theme
    assert chips == [("chip-normal", "#1E6B3D", "#E3F3E9")], chips
    with open(DEFAULT_SCRIPT, encoding="utf-8") as f:
        assert not report(f.read(), "#FAFAF8")
    print("self-test passed")
    return 0


def main(argv):
    if argv and argv[0] == "--self-test":
        return self_test()
    canvas = "#FAFAF8"
    if "--canvas" in argv:
        i = argv.index("--canvas")
        canvas = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    path = argv[0] if argv else DEFAULT_SCRIPT
    with open(path, encoding="utf-8") as f:
        failures = report(f.read(), canvas)
    if failures:
        print("\nbelow 4.5:1: " + ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
