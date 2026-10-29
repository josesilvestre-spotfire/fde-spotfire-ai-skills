# What Spotfire's text-area sanitizer keeps

Spotfire Analyst 15.0 sanitizes text-area HTML when it renders the text area, by default (the
preference `PerformHtmlSanitation`). The HTML is stored as written. An analysis authored where
sanitizing is off can look right there and lose its styling, controls and whole blocks on every
other machine. Write for the sanitizer, always.

These results come from running Spotfire 15.0's own sanitizer over text-area HTML, including a
styling template's demo text areas and a set of snippets built to pass it.
`scripts/check_textarea_html.py` applies the same rules offline.

## Elements

| Kept | Removed with everything inside |
|---|---|
| `div span p h1-h6 table thead tbody tfoot tr td th col colgroup ul ol li dl dt dd b strong i em u strike del ins font br hr pre code blockquote q cite abbr acronym label a img dir` | `style script link meta iframe svg canvas form input select textarea button details summary section article header footer nav main aside figure figcaption small sub sup s mark caption video audio object embed center` |

What that removal cost in practice:

| Construct | Result | Use instead |
|---|---|---|
| `<details><summary>` accordion | the element and everything in it go: one demo area fell from 5,606 to 100 characters, 96 elements lost with it | tabs (`.tabbed-content`) or plain sections, a heading and a table per section |
| `<input>` used as a demo text box | removed | a Spotfire input control |
| toggle switch built on `<input type="checkbox">` | removed | a checkbox control (a Yes/No drop-down), a radio list box, or two buttons |
| `<style>` in the HTML | removed | the injector script |
| `<svg>` icons | removed | text, or a character in a styled `span` |

Controls placed inside a removed element are lost with it.

## Attributes

- Kept on every element: `style`, `class`, `id`, `dir`, `lang`. Blocks also keep `align`; tables
  and cells keep their layout attributes (`cellspacing`, `cellpadding`, `colspan`, `rowspan`,
  `width`, `valign`).
- `a` keeps `href` (`https:` and `#anchor` were tested), `title`, `target`, `class`, `id`. `style`
  and `rel` on a link are removed.
- Removed everywhere: `data-*` attributes and `on*` event handlers.
- Keep class and id values to letters, digits, `-` and `_`.

## Inline styles

- Plain values only. A `style` attribute that uses `var(--...)` is dropped whole: one demo area
  lost 56 `style` attributes this way. Treat `calc()`, `url()` and gradients the same.
- Kept: plain colors (`#B42318`, `rgba(0, 0, 0, 0.15)`), lengths in px and %, `!important`.
- Avoid quoted values (font names) in inline styles: set fonts in the stylesheet.
- One rejected declaration drops the whole attribute, so keep inline styles short.

## Other rules

- `${PropertyName}` is not substituted in text-area HTML. Show a property's value with a label
  control bound to it.
- Images come from the text area's own image collection, never from external URLs.
- Balanced markup: the sanitizer repairs stray end tags and can move content while it does.
- Text-area JavaScript is not part of the HTML. It is attached to the text area, runs after every
  full render of that text area with Spotfire's jQuery available as `$`, and does not run again
  when a control value changes.

## How controls render (the DOM your CSS targets)

| Control | Spotfire renders | Notes |
|---|---|---|
| button | `input[type=button].sfc-action-button` | form controls do not inherit `text-transform`; style the input itself. Spotfire may write an inline pixel width that beats a width set in the stylesheet |
| text input | `<input type="text">`, most likely with the class `sfc-text-box` | the class is read from the renderer, not seen live: target `input[type=text]` |
| multi-line input | `<textarea>` with the same text-box class | |
| drop-down, checkbox | `div.sf-element-dropdown` (`.ComboBoxTextDivContainer`, `.sf-element-dropdown-list-item` when open) | width set by Spotfire |
| list box, multi-select list box, radio | `div.sf-element-list-box` > `.sf-element-list-box-item`; selected rows `.sfpc-selected` | |
| slider | `span.TextAreaSlider` with `.sf-element-range`, `.sf-element-thumb`, `.ValueLabel`, `.MinLabel`, `.MaxLabel` | a stylesheet that sets these classes page-wide also restyles the filter sliders; one that gave the track no height made text-area sliders invisible |
| label | a `span` holding the formatted value | inherits the wrapper's class (`dashboard-value`, `body-text2`) |
| link | `<a href="javascript:void(0);">` | looks like a link; prefer a button for navigation |

- A drop-down inside a block hidden with `display: none` renders zero wide when the block is
  shown (seen in Analyst 15.0). Hide blocks off screen (`position: absolute; left: -10000px`), as
  the injector's tabs do.
- Placeholders for controls (`{{control:<id>}}` in this skill's snippets) go inside a `div`,
  `span`, `p`, `td` or `li`. Each control is placed once.
