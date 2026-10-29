/*
 * Apply App Styles
 *
 * Attach this JavaScript to ONE text area per page: the host. The host's
 * HTML starts with <div id="style-container"></div><div id="styleDivSF"></div>.
 * Spotfire removes <style> elements from text-area HTML, so this script
 * writes the stylesheet into the page each time the host renders. The
 * stylesheet then applies to every text area on that page.
 *
 * Every rule is scoped under the class "app-ta". Wrap the content of each
 * text area you want styled in <div class="app-ta">...</div>. Nothing
 * outside that wrapper is touched, so the filter panel, the data canvas,
 * visual titles and Spotfire's own dialogs keep their own look. Visual
 * titles, fonts and backgrounds of the visuals come from the theme JSON.
 *
 * The script also switches tabs in ".tabbed-content" blocks (links with
 * href="#<item id>"), because the sanitizer removes inline event handlers.
 *
 * Change the look in THEME only. Fonts are system and Spotfire fonts, so
 * nothing is downloaded and the look is the same offline.
 */
(function () {
    "use strict";

    var STYLE_ID = "app-styles";
    var THEME = {
        font: "Roboto, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
        mono: "Consolas, 'Cascadia Mono', 'Courier New', monospace",
        ink: "#1F2328",          // body text, 15:1 on the canvas
        muted: "#5B6370",        // captions and hints, 5.8:1
        line: "#D0D5DD",         // borders and rules
        panel: "#FFFFFF",        // raised card
        soft: "#F3F4F6",         // muted card, tab strip
        accent: "#3050EF",       // buttons, active tab, KPI values, 5.7:1
        accentHover: "#2440D6",
        accentPressed: "#1B32AB",
        accentTint: "#E8ECFD",
        success: "#1E7A47",
        danger: "#B42318"
    };

    function stylesheet(t) {
        var s = ".app-ta";
        return [
            s + " { font-family: " + t.font + "; font-size: 12px; line-height: 1.45; color: " + t.ink + "; }",
            s + " p { margin: 0 0 6px 0; }",
            s + " a { color: " + t.accent + "; text-decoration: none; }",
            s + " a:hover { text-decoration: underline; }",

            // Headings: panel title, card titles, section and field labels.
            s + " .heading { margin: 4px 0 8px 0; font-size: 15px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }",
            s + " .subheading-lg { margin: 6px 0; font-size: 14px; font-weight: 600; }",
            s + " .subheading-md { margin: 5px 0; font-size: 13px; font-weight: 600; }",
            s + " .subheading { margin: 5px 0; font-size: 11px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: " + t.muted + "; }",

            // Layout tables: raised card, muted card, flat.
            s + " .table1, " + s + " .table2, " + s + " .table3 { width: 100%; border-collapse: separate; border-spacing: 0; }",
            s + " .table1 { background: " + t.panel + "; border: 1px solid " + t.line + "; border-radius: 6px; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.06); }",
            s + " .table2 { background: " + t.soft + "; border: 1px solid " + t.line + "; border-radius: 6px; }",
            s + " .table1 td, " + s + " .table2 td, " + s + " .table3 td { padding: 4px 8px; vertical-align: middle; }",
            s + " .sectiontd { border-bottom: 1px solid " + t.line + "; }",
            s + " .sectionbreak { height: 1px; margin: 8px 0; background: " + t.line + "; }",
            s + " td.leftAlignedInputField { text-align: left; }",

            // Text utilities.
            s + " .body-text { color: " + t.muted + "; }",
            s + " .body-text2 { color: " + t.ink + "; }",
            s + " .numeric-text { font-variant-numeric: tabular-nums; text-align: right; }",
            s + " .sf-label { font-size: 10px; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; color: " + t.muted + "; }",
            s + " .sf-hint { font-size: 11px; font-style: italic; color: " + t.muted + "; }",
            s + " .sf-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }",
            s + " pre { margin: 6px 0; padding: 6px 10px; border-left: 3px solid " + t.accent + "; background: " + t.soft + "; font-family: " + t.mono + "; font-size: 12px; white-space: pre-wrap; }",

            // KPI band: caption and value only, one tooltip per card.
            s + " .kpi-cell { padding: 2px 10px; border-right: 1px solid " + t.line + "; vertical-align: top; }",
            s + " .kpi-cell:last-child { border-right: none; }",
            s + " .dashboard-value { font-size: 26px; font-weight: 600; line-height: 1.2; color: " + t.accent + "; font-variant-numeric: tabular-nums; }",
            s + " .dashboard-numeric { font-family: " + t.mono + "; font-size: 24px; font-weight: 600; color: " + t.accent + "; }",
            s + " .dashboard-label { font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: " + t.muted + "; }",

            // Spotfire's text-area controls, inside styled text areas only.
            s + " input[type=button].sfc-action-button { min-height: 28px; padding: 0 12px; border: 1px solid " + t.accent + "; border-radius: 4px; background: " + t.panel + "; color: " + t.accent + "; font-family: " + t.font + "; font-size: 12px; font-weight: 600; cursor: pointer; }",
            s + " input[type=button].sfc-action-button:hover { background: " + t.accentTint + "; }",
            s + " input[type=button].sfc-action-button:active { background: " + t.accentPressed + "; border-color: " + t.accentPressed + "; color: #FFFFFF; }",
            s + " .key-btn input[type=button].sfc-action-button { background: " + t.accent + "; color: #FFFFFF; }",
            s + " .key-btn input[type=button].sfc-action-button:hover { background: " + t.accentHover + "; border-color: " + t.accentHover + "; }",
            s + " .sav-btn input[type=button].sfc-action-button:hover { background: " + t.success + "; border-color: " + t.success + "; color: #FFFFFF; }",
            s + " .del-btn input[type=button].sfc-action-button { border-color: " + t.line + "; color: " + t.ink + "; }",
            s + " .del-btn input[type=button].sfc-action-button:hover { background: " + t.danger + "; border-color: " + t.danger + "; color: #FFFFFF; }",
            s + " input[type=text], " + s + " textarea { border: 1px solid " + t.line + "; border-radius: 3px; padding: 2px 6px; font-family: " + t.font + "; font-size: 12px; color: " + t.ink + "; background: " + t.panel + "; }",
            s + " input[type=text]:focus, " + s + " textarea:focus { outline: none; border-color: " + t.accent + "; }",

            // CSS tooltips: an info mark that shows one or two sentences on hover.
            s + " .tooltip-container { position: relative; display: inline-block; cursor: help; }",
            s + " .info-icon { display: inline-block; width: 13px; height: 13px; margin-left: 4px; border: 1px solid " + t.muted + "; border-radius: 50%; color: " + t.muted + "; font-size: 9px; font-style: normal; font-weight: 700; line-height: 13px; text-align: center; text-transform: none; vertical-align: 1px; }",
            s + " .tooltip { display: none; position: absolute; z-index: 20; left: 18px; top: -4px; width: 220px; padding: 6px 8px; border: 1px solid " + t.line + "; border-radius: 4px; background: " + t.panel + "; box-shadow: 0 4px 12px rgba(16, 24, 40, 0.15); color: " + t.ink + "; font-size: 11px; font-weight: 400; letter-spacing: 0; line-height: 1.4; text-transform: none; white-space: normal; }",
            s + " .tooltip-container:hover .tooltip { display: block; }",
            s + " .tooltip-container.flip .tooltip { left: auto; right: 18px; }",

            // Tabs. Inactive items move off screen instead of display: none,
            // because a drop-down inside a hidden block renders zero wide.
            s + " .tabbed-content { position: relative; }",
            s + " .tabbed-content .tabs ul { display: flex; margin: 0 0 6px 0; padding: 0; list-style: none; border-bottom: 1px solid " + t.line + "; }",
            s + " .tabbed-content .tabs li { margin: 0; }",
            s + " .tabbed-content .tabs a { display: block; padding: 6px 12px; color: " + t.muted + "; font-weight: 600; border-bottom: 2px solid transparent; }",
            s + " .tabbed-content .tabs a.active { color: " + t.accent + "; border-bottom-color: " + t.accent + "; }",
            s + " .tabbed-content .item { position: absolute; left: -10000px; top: 0; width: 100%; visibility: hidden; }",
            s + " .tabbed-content .item.active { position: static; visibility: visible; }",

            // Status chips: text on tint, 5.6:1 or more.
            s + " .sf-badge { display: inline-block; padding: 1px 8px; border: 1px solid " + t.line + "; border-radius: 9px; background: " + t.soft + "; color: " + t.ink + "; font-size: 10px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; }",
            s + " .chip-normal { background: #E3F3E9; border-color: #93D1AC; color: #1E6B3D; }",
            s + " .chip-warning { background: #FFF5D1; border-color: #F2D46B; color: #6E5200; }",
            s + " .chip-alarm { background: #FDEAD8; border-color: #F5B27A; color: #8A4100; }",
            s + " .chip-critical { background: #FBE4E1; border-color: #EFA39B; color: #9C1F16; }",
            s + " .chip-offline { background: #EFEFEF; border-color: #BDBDBD; color: #4D4D4D; }",
            s + " .chip-info { background: " + t.accentTint + "; border-color: #AEBBF7; color: " + t.accentPressed + "; }"
        ].join("\n");
    }

    function inject() {
        var host = document.getElementById("style-container") ||
            document.getElementById("styleDivSF");
        if (!host) {
            return;
        }
        // One stylesheet per page: remove an earlier copy before adding.
        var old = document.getElementById(STYLE_ID);
        if (old && old.parentNode) {
            old.parentNode.removeChild(old);
        }
        var style = document.createElement("style");
        style.id = STYLE_ID;
        style.appendChild(document.createTextNode(stylesheet(THEME)));
        host.appendChild(style);
    }

    function closest(node, className) {
        while (node && node.nodeType === 1) {
            if ((" " + node.className + " ").indexOf(" " + className + " ") >= 0) {
                return node;
            }
            node = node.parentNode;
        }
        return null;
    }

    function onTabClick(event) {
        var link = event.target;
        while (link && link.nodeType === 1 && link.tagName !== "A") {
            link = link.parentNode;
        }
        if (!link || link.nodeType !== 1 || !closest(link, "tabs")) {
            return;
        }
        var block = closest(link, "tabbed-content");
        var href = link.getAttribute("href") || "";
        if (!block || href.charAt(0) !== "#") {
            return;
        }
        event.preventDefault();
        var links = block.querySelectorAll(".tabs a");
        var items = block.querySelectorAll(".item");
        var i;
        for (i = 0; i < links.length; i++) {
            links[i].className = links[i].className.replace(/\s*\bactive\b/g, "");
        }
        for (i = 0; i < items.length; i++) {
            items[i].className = items[i].className.replace(/\s*\bactive\b/g, "");
        }
        link.className += " active";
        var target = document.getElementById(href.substring(1));
        if (target) {
            target.className += " active";
        }
    }

    inject();
    // The script runs after every render of the host; bind the tab handler once.
    if (!window.appStylesTabsBound) {
        document.addEventListener("click", onTabClick, true);
        window.appStylesTabsBound = true;
    }
})();
