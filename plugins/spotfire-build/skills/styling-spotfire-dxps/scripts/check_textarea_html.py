"""Check text-area HTML against Spotfire's HTML sanitizer rules.

Spotfire Analyst 15.0 sanitizes text-area HTML when it renders it, by
default. The stored HTML stays as written, so a text area can look right on
a machine where sanitizing is turned off and lose its styling and controls
everywhere else. This check applies the rules observed with Spotfire 15.0's
sanitizer offline, without Spotfire:

  errors    elements the sanitizer removes with everything inside them
            (style, script, svg, input, select, button, form, details, ...),
            on* handlers, data-* attributes, style or rel on links, inline
            styles that use var(), calc(), url() or gradients, ${...}
            references (not substituted in text areas), control placeholders
            used twice or placed outside div, span, p, td or li, unbalanced
            tags, external images, the two host divs outside the host
  warnings  unknown elements, class or id values with other characters than
            letters, digits, - and _, links other than https:, http: or
            #anchor, text areas without the "app-ta" wrapper class, quoted
            font names in inline styles

Control placeholders are written {{control:<id>}}; each becomes one Spotfire
control (inserted by hand in the text area editor, or by a builder).

Usage:
  python check_textarea_html.py FILE_OR_FOLDER [...]
  python check_textarea_html.py --self-test

A file whose HTML starts with the two host divs is treated as the page's
host. Exit code 1 when any error is found. Standard library only.
"""

import os
import re
import sys
from html.parser import HTMLParser

ALLOWED = set("""div span p h1 h2 h3 h4 h5 h6 table thead tbody tfoot tr td th col
colgroup ul ol li dl dt dd b strong i em u strike del ins font br hr pre code
blockquote q cite abbr acronym label a img dir spotfirecontrol""".split())
REMOVED = set("""style script link meta iframe svg canvas form input select
textarea button details summary section article header footer nav main aside
figure figcaption small sub sup s mark caption video audio object embed
center""".split())
VOID = {"br", "hr", "img", "col", "input", "meta", "link"}
GLOBAL_ATTRS = {"style", "class", "id", "dir", "lang"}
BLOCK_ATTRS = {"align"}
TABLE_ATTRS = {"cellspacing", "cellpadding", "border", "width", "height",
               "colspan", "rowspan", "valign", "align", "span", "summary"}
LINK_ATTRS = {"href", "title", "target", "class", "id"}
PLACEHOLDER_PARENTS = {"div", "span", "p", "td", "li"}
PLACEHOLDER = re.compile(r"\{\{control:([A-Za-z][A-Za-z0-9]*)\}\}")
NAME_VALUE = re.compile(r"^[A-Za-z0-9_\- ]*$")
BAD_STYLE = re.compile(r"var\(|calc\(|url\(|gradient\(|expression\(", re.I)
HOST_START = '<div id="style-container"></div><div id="styleDivSF"></div>'


class Checker(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.found, self.ids = [], [], {}
        self.removed_depth = 0
        self.has_wrapper = False

    def add(self, level, text):
        self.found.append((level, self.getpos()[0], text))

    def handle_starttag(self, tag, attrs):
        self.check_tag(tag, attrs)
        if tag not in VOID:
            self.stack.append(tag)
            if tag in REMOVED:
                self.removed_depth += 1

    def handle_startendtag(self, tag, attrs):
        self.check_tag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.add("ERROR", "</%s> without an opening tag" % tag)
            return
        if self.stack[-1] != tag:
            self.add("ERROR", "</%s> closes <%s>: unbalanced tags (the "
                     "sanitizer repairs them and may move content)"
                     % (tag, self.stack[-1]))
            if tag in self.stack:
                while self.stack and self.stack[-1] != tag:
                    self.pop()
                self.pop()
            return
        self.pop()

    def pop(self):
        tag = self.stack.pop()
        if tag in REMOVED:
            self.removed_depth -= 1

    def check_tag(self, tag, attrs):
        if tag in REMOVED:
            self.add("ERROR", "<%s> is removed with everything inside it"
                     % tag)
        elif tag not in ALLOWED:
            self.add("WARNING", "<%s> is not in the list of kept elements"
                     % tag)
        allowed = set(GLOBAL_ATTRS) | BLOCK_ATTRS
        if tag in ("table", "tr", "td", "th", "col", "colgroup", "thead",
                   "tbody", "tfoot"):
            allowed |= TABLE_ATTRS
        if tag == "a":
            allowed = set(LINK_ATTRS)
        if tag == "img":
            allowed |= {"src", "alt", "width", "height"}
        for name, value in attrs:
            value = value or ""
            if name.startswith("on"):
                self.add("ERROR", "%s on <%s>: event handlers are removed"
                         % (name, tag))
            elif name.startswith("data-"):
                self.add("ERROR", "%s on <%s>: data-* attributes are removed"
                         % (name, tag))
            elif tag == "a" and name in ("style", "rel"):
                self.add("ERROR", "%s on <a> is removed" % name)
            elif name not in allowed:
                self.add("WARNING", "%s on <%s> may be removed" % (name, tag))
            if name == "style":
                if BAD_STYLE.search(value):
                    self.add("ERROR", "inline style on <%s> uses var(), "
                             "calc(), url() or a gradient: the whole style "
                             "attribute is dropped" % tag)
                if "'" in value or '"' in value:
                    self.add("WARNING", "quoted value in the inline style on "
                             "<%s>: set fonts in the stylesheet instead" % tag)
            if name in ("class", "id") and not NAME_VALUE.match(value):
                self.add("WARNING", "%s=\"%s\" on <%s>: use letters, digits, "
                         "- and _" % (name, value, tag))
            if name == "class" and "app-ta" in value.split():
                self.has_wrapper = True
            if name == "id":
                if value in self.ids:
                    self.add("ERROR", "id \"%s\" is used twice" % value)
                self.ids[value] = True
            if tag == "a" and name == "href" and not re.match(
                    r"^(https?:|#)", value):
                self.add("WARNING", "href \"%s\": use https: or #anchor"
                         % value)
            if tag == "img" and name == "src" and re.match(
                    r"^(https?:|//)", value):
                self.add("ERROR", "external image: use the text area's own "
                         "image collection")

    def handle_data(self, data):
        if "${" in data:
            self.add("ERROR", "${...} is not substituted in text-area HTML: "
                     "use a label control bound to the property")
        for _ in PLACEHOLDER.finditer(data):
            parent = self.stack[-1] if self.stack else "(top level)"
            if parent not in PLACEHOLDER_PARENTS:
                self.add("ERROR", "control placeholder inside <%s>: place "
                         "it in a div, span, p, td or li" % parent)
            if self.removed_depth:
                self.add("ERROR", "control placeholder inside a removed "
                         "element is lost")


def check_html(text, host=None):
    """Return a list of (level, line, message)."""
    if host is None:
        host = text.lstrip().startswith(HOST_START)
    checker = Checker()
    checker.feed(text)
    checker.close()
    found = list(checker.found)
    for tag in checker.stack:
        found.append(("ERROR", 0, "<%s> is never closed" % tag))
    seen = {}
    for m in PLACEHOLDER.finditer(text):
        seen[m.group(1)] = seen.get(m.group(1), 0) + 1
    for name, count in sorted(seen.items()):
        if count > 1:
            found.append(("ERROR", 0, "control %s is placed %d times: each "
                          "control is placed exactly once" % (name, count)))
    has_hooks = 'id="style-container"' in text or 'id="styleDivSF"' in text
    if host and not text.lstrip().startswith(HOST_START):
        found.append(("ERROR", 1, "the host must start with " + HOST_START))
    if not host and has_hooks:
        found.append(("ERROR", 0, "only the page's host text area has the "
                      "style-container and styleDivSF divs"))
    if not checker.has_wrapper:
        found.append(("WARNING", 0, "no element with class \"app-ta\": the "
                      "stylesheet does not style this text area"))
    return sorted(found, key=lambda f: (f[1], f[0]))


def iter_files(paths):
    for path in paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.lower().endswith((".html", ".htm")):
                    yield os.path.join(path, name)
        else:
            yield path


SELF_TEST_BAD = """<div class="app-ta">
<style>.x { color: red; }</style>
<details><summary>More</summary>{{control:lost}}</details>
<div style="color: var(--ink)" data-role="x" onclick="go()">Value ${MinPoints}</div>
<a href="javascript:run()" style="color: red" rel="noopener">Run</a>
<table><tr>{{control:inRow}}</tr></table>
<span>{{control:twice}}</span><span>{{control:twice}}</span>
<p><span>unclosed</p>
</div>
"""

SELF_TEST_GOOD = HOST_START + """
<div class="app-ta"><h2 class="heading">Title</h2>
<table class="table3"><tbody><tr><td class="key-btn">{{control:runAnalysis}}</td></tr></tbody></table>
<span class="tooltip-container"><i class="info-icon">i</i><span class="tooltip">Tip.</span></span>
<a href="https://example.com/guide" target="_blank">Guide</a>
</div>
"""


def self_test():
    bad = check_html(SELF_TEST_BAD)
    text = " | ".join(m for _, _, m in bad)
    for expected in ("<style> is removed", "<details> is removed",
                     "placeholder inside a removed", "var()",
                     "data-* attributes", "event handlers",
                     "${...}", "style on <a>", "rel on <a>",
                     "placeholder inside <tr>", "control twice is placed 2",
                     "closes <span>"):
        assert expected in text, (expected, text)
    good = check_html(SELF_TEST_GOOD)
    assert not good, good
    not_host = check_html('<div class="app-ta">' + HOST_START + "</div>",
                          host=False)
    assert any("only the page's host" in m for _, _, m in not_host)
    print("self-test passed")
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--self-test":
        return self_test()
    errors = 0
    for path in iter_files(argv):
        with open(path, encoding="utf-8") as f:
            found = check_html(f.read())
        errors += len([f for f in found if f[0] == "ERROR"])
        print("%s: %s" % (path, "ok" if not found else
                          "%d finding(s)" % len(found)))
        for level, line, message in found:
            print("  %s line %d: %s" % (level, line, message))
    print("%d error(s)" % errors)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
