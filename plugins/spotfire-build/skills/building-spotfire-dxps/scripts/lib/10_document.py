# ============================================================================
# 10_document.py - document-level start and finish of a build:
#   doc_prepare      snapshot of the pages the starting document already has
#   doc_apply_theme  writes build/theme.json; the theme itself is a manual step
#   doc_finish       remove the pre-existing pages, final page titles, page
#                    navigation, canvas size, active page, description, keywords
# IronPython 3.4 (no f-strings, walrus, annotations, print or tabs).
# Requires newer than 14.6: none (newest public members: Page.Visible and
# PageNavigationMode.Off, api 10.7).
# Public API only: the document theme has no public API, so doc_apply_theme raises
# after writing build/theme.json and the build records a manual step.
# BCL: System.Drawing.Size, System.Enum.Parse, List[str], System.IO.File/Directory/Path.
# ============================================================================
import clr
clr.AddReference("System.Drawing")
import json
from System import Enum
from System.Collections.Generic import List
from System.Drawing import Size
from System.IO import File, Directory, Path
from Spotfire.Dxp.Application import PageNavigationMode

_document_themes = ("LightSfx", "DarkSfx", "Light", "Dark")
_document_navigation_modes = ("Tabs", "Links", "None", "Off")


# ---- doc.prepare -------------------------------------------------------------
def doc_prepare():
    """Remember the pages the starting document already has (a blank analysis has "Page" and
    sometimes "Cover Page"). Nothing is removed here: doc_finish removes them once the spec
    pages exist, so the document never has zero pages. Returns the snapshot. (Starter data
    tables are handled by 90_build: renamed on a name clash, removed after doc_finish.)"""
    old = [p for p in B.doc.Pages]          # snapshot: never mutate a collection while iterating it
    B.document_old_pages = old
    info = B.created.setdefault("document", {})
    info["preExistingPages"] = [p.Title for p in old]
    return old


# ---- theme -------------------------------------------------------------------
def doc_apply_theme(theme):
    """The document theme has no public API in Spotfire 15.0. This step writes the custom styles to
    build/theme.json (when app.theme gives them), records what to apply, and raises, so 90_build's
    B.step turns it into a manual step."""
    theme = theme or {}
    base = theme.get("base") or "LightSfx"
    if base not in _document_themes:
        raise Exception("app.theme.base must be one of " + ", ".join(_document_themes) + " (got "
                        + repr(base) + ")")
    styles = theme.get("customStyles")
    text = _document_styles_json(styles, base) if styles else None
    path = _document_write_theme_file(text)
    B.created["theme"] = {"base": base, "customStyles": text is not None, "file": path,
                          "applied": False}
    raise Exception("no public API sets the document theme")


def _document_styles_json(styles, base):
    """Compact theme-editor JSON for CustomStylesJson. general.baseTheme and general.baseThemeSfx
    are set to app.theme.base: Spotfire reads general.baseTheme directly when it builds the
    style sheet (IL, Document.GetCustomStyleSheetText), so the base must be the exact theme name."""
    if isinstance(styles, str):
        # the resolved spec carries a dict; accept JSON text or a path defensively
        source = styles.strip()
        if not source.startswith("{"):
            source = File.ReadAllText(B.path(source))
        styles = json.loads(source)
    if not isinstance(styles, dict):
        raise Exception("app.theme.customStyles must be a theme-editor JSON object")
    styles = json.loads(json.dumps(styles))          # private copy; the spec stays untouched
    general = styles.get("general")
    if not isinstance(general, dict):
        general = {}
        styles["general"] = general
    named = general.get("baseThemeSfx") or general.get("baseTheme")
    if named and named != base:
        B.warn("app.theme.customStyles names base theme '" + str(named) + "' but app.theme.base is '"
               + base + "'; the builder uses '" + base + "'")
    general["baseTheme"] = base
    general["baseThemeSfx"] = base
    return json.dumps(_document_json_ints(styles), separators=(",", ":"), sort_keys=True)


def _document_json_ints(value):
    """Spotfire reads theme numbers as integers (JsonBundle.GetInt): 4.0 becomes 4."""
    if isinstance(value, dict):
        return dict((k, _document_json_ints(value[k])) for k in value)
    if isinstance(value, list):
        return [_document_json_ints(v) for v in value]
    if isinstance(value, float) and value == value and abs(value) < 1e15 and value == int(value):
        return int(value)
    return value


def _document_write_theme_file(text):
    """build/theme.json = the custom styles as applied (pretty-printed). Removed when the spec has
    no custom styles, so a stale file never misleads. A write failure is only a warning."""
    path = Path.Combine(B.build_dir(), "theme.json")
    try:
        if text is None:
            if File.Exists(path):
                File.Delete(path)
            return None
        Directory.CreateDirectory(B.build_dir())
        File.WriteAllText(path, json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n")
        return path
    except Exception as e:
        B.warn("could not write " + path + ": " + exc_text(e))
        return None


# ---- doc.finish --------------------------------------------------------------
def doc_finish():
    """Last build step: each item is its own B.step so one failure never blocks the others."""
    info = B.created.setdefault("document", {})
    built = _document_built_pages()
    _document_remove_old_pages(built)
    if B.doc.Pages.Count == 0:
        B.step("ensurePage", B.app.get("name", ""), _document_ensure_page)
    titles = info.setdefault("pageTitles", {})
    for title, page in built:
        titles[title] = B.step("pageTitle", title, _document_final_title, (page, title),
                               fallback="Rename the page (its current title is in 'why') to '" + str(title)
                                        + "'; page titles are unique, so rename or delete any other page "
                                        "with that title first.")
    mode = B.app.get("pageNavigation") or "Tabs"
    B.step("navigation", mode, _document_navigation, (mode,),
           fallback="Set the page navigation of the analysis to '" + str(mode) + "'.")
    canvas = B.app.get("canvas")
    size = "default" if not canvas else str(canvas.get("width")) + "x" + str(canvas.get("height"))
    B.step("canvas", size, _document_canvas, (canvas,),
           fallback=("Set the visualization area to a fixed size of " + size + " pixels"
                     + (" (fit to window)" if canvas and canvas.get("fitToWindow", True) else "") + "."
                     if canvas else "Leave the visualization area at its default (fit to window)."))
    wanted = B.spec.get("activePage")
    if built:
        B.step("activePage", wanted or "(first page)", _document_active_page, (built,),
               fallback="Make the page '" + str(wanted or built[0][0]) + "' the active page before saving.")
    else:
        B.skip("activePage", wanted or "(first page)", "no spec page was created")
    B.step("description", B.app.get("name", ""), _document_description,
           (B.app.get("description") or "",),
           fallback="Set the analysis description (document properties) to: " + (B.app.get("description") or ""))
    B.step("keywords", B.app.get("name", ""), _document_keywords, (B.app.get("keywords") or [],),
           fallback="Set the analysis keywords (document properties) to: "
                    + "; ".join([str(k) for k in (B.app.get("keywords") or [])]))
    info["pageOrder"] = [p.Title for p in B.doc.Pages]
    return info


def _document_built_pages():
    """(spec title, page) for every spec page that pages_create registered, in spec order."""
    out = []
    seen = set()
    for pspec in B.spec.get("pages", []):
        title = pspec.get("title")
        if title in seen or title not in B.created["pages"]:
            continue
        seen.add(title)
        page = B.page(title)
        if B.doc.Pages.Contains(page):
            out.append((title, page))
    return out


def _document_remove_old_pages(built):
    """Remove the pages snapshotted by doc_prepare - only once spec pages exist, never the last
    page (PageCollection.Remove has no guard and would leave zero pages, IL)."""
    old = getattr(B, "document_old_pages", None) or []
    if not old:
        return 0
    if not built:
        B.warn("no spec page was created, so the " + str(len(old)) + " pre-existing page(s) were kept "
               "(an analysis always needs one page)")
        return 0
    keep = set(str(page.Id) for title, page in built)
    removed = 0
    for page in old:
        if str(page.Id) in keep or not B.doc.Pages.Contains(page):
            continue
        title = page.Title
        if B.step("removePage", title, _document_remove_page, (page,),
                  fallback="Delete the page '" + title + "' (it came from the starting document)."):
            removed += 1
    B.created["document"]["removedPages"] = removed
    return removed


def _document_remove_page(page):
    if B.doc.Pages.Count <= 1:
        raise Exception("kept: it is the only page left in the document")
    if not B.doc.Pages.Remove(page):
        raise Exception("PageCollection.Remove returned False")
    return True


def _document_ensure_page():
    """Only reachable when the starting document had no page and no spec page was built."""
    page = B.doc.Pages.AddNew(B.app.get("name") or "Page")
    B.warn("the document had no page left; added an empty page '" + page.Title + "'")
    return page


def _document_final_title(page, title):
    """Temporary title -> spec title, read back. The setter trims and makes titles unique
    case-insensitively ('X (2)'), so a clash shows up here. Titles containing '$' are
    preprocessor expressions whose getter returns the evaluated text: not compared."""
    # Not yet tested: page titles with ${...} evaluate like visual titles, and an escaped '\${'
    # reads back as a literal '${'.
    before = page.Title
    try:
        page.Title = title
    except Exception as e:
        raise Exception("the page keeps the title '" + str(before) + "': " + exc_text(e))
    actual = page.Title
    if "$" not in title and actual != title:
        raise Exception("Spotfire renamed the page to '" + actual + "' (page titles are unique, "
                        "case-insensitive, trimmed)")
    return actual


def _document_navigation(mode):
    if mode not in _document_navigation_modes:
        raise Exception("app.pageNavigation must be one of " + ", ".join(_document_navigation_modes)
                        + " (got " + repr(mode) + ")")
    # 'PageNavigationMode.None' is a syntax error in Python 3: always look the member up by name.
    # Not yet tested: getattr returns the None member (value 2); how None and Off render in the
    # 15.0 page bar.
    value = getattr(PageNavigationMode, mode, None)
    if value is None:
        value = Enum.Parse(clr_type(PageNavigationMode), mode)
    B.doc.Pages.NavigationMode = value
    if B.doc.Pages.NavigationMode != value:
        raise Exception("NavigationMode reads back " + str(B.doc.Pages.NavigationMode))
    B.created["document"]["navigationMode"] = mode
    return mode


def _document_canvas(canvas):
    """app.canvas -> Document.Pages.VisualizationAreaSize. No canvas = Spotfire's default
    (Size.Empty, FitToWindow=True), set explicitly so a non-blank start cannot leak through."""
    if canvas:
        width = int(canvas.get("width") or 0)
        height = int(canvas.get("height") or 0)
        if width <= 0 or height <= 0:
            raise Exception("app.canvas needs a positive width and height")
        fit = bool(canvas.get("fitToWindow", True))
    else:
        width, height, fit = 0, 0, True
    # Not yet tested: how a fixed Size combines with FitToWindow=True when rendered
    # (a GUI-built DXP persists 1920x2000 with FitToWindow true).
    area = B.doc.Pages.VisualizationAreaSize
    area.Size = Size(width, height)
    area.FitToWindow = fit
    if area.Size.Width != width or area.Size.Height != height or area.FitToWindow != fit:
        raise Exception("VisualizationAreaSize reads back " + str(area.Size.Width) + "x"
                        + str(area.Size.Height) + " fitToWindow=" + str(area.FitToWindow))
    B.created["document"]["canvas"] = {"width": width, "height": height, "fitToWindow": fit}
    return area


def _document_active_page(built):
    """Spec activePage, else the first visible spec page, else the first spec page. Set last:
    PageCollection.AddNew makes every new page the active one (IL)."""
    if not built:
        raise Exception("no spec page was created")
    wanted = B.spec.get("activePage")
    title, page = None, None
    if wanted:
        for t, p in built:
            if t == wanted:
                title, page = t, p
                break
        if page is None:
            B.warn("activePage '" + str(wanted) + "' was not built; the first page is active instead")
        elif not page.Visible:
            B.warn("activePage '" + title + "' is a hidden page")
    if page is None:
        visible = [(t, p) for t, p in built if p.Visible]
        title, page = (visible or built)[0]
    B.doc.ActivePageReference = page
    B.created["document"]["activePage"] = title
    return page


def _document_description(text):
    B.doc.Properties.Description = text
    B.created["document"]["description"] = text
    return text


def _document_keywords(words):
    """DocumentProperties.Keywords is IList<String>: a Python list does not convert."""
    wanted = [str(w) for w in words]
    B.doc.Properties.Keywords = List[str](wanted)
    # Not yet tested: the keywords persist in the saved file.
    actual = [k for k in B.doc.Properties.Keywords]
    if actual != wanted:
        raise Exception("Keywords read back as " + repr(actual))
    B.created["document"]["keywords"] = wanted
    return wanted
