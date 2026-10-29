# Develop, test and deliver

## Project layout (plain JavaScript, no build step)

```
<mod-name>/
  src/mod-manifest.json
  src/index.html        loader script copied from an official example
  src/main.js           the mod
  src/main.css
  src/icon.svg
  package.json          "server": "mods-dev-server src", "test": "node test-harness.js"
  test-harness.js       jsdom test against a mock of the mod API
  README.md             setup, connection, axis wiring table, aggregation None
```

No bundler, no TypeScript, no external libraries: hand-written SVG or canvas. A TypeScript
project from the official SDK (`@spotfire/mods-sdk`) works too; the rules in this skill apply to
both.

Reference material: the official spotfire-mods repository. Download it as a tarball from
codeload (`https://codeload.github.com/spotfiresoftware/spotfire-mods/tar.gz/refs/heads/master`;
the branch is `master`) instead of the GitHub API, which rate-limits anonymous calls. The plain
JavaScript examples show the loader snippet and the render loop.

## Development loop

1. Node 22 or later. On Windows PowerShell, use `npm.cmd` when the execution policy blocks
   `npm.ps1`.
2. `npm install`, then `npm run server`: the development server listens on port 8090.
3. In Analyst: Tools > Development > Mods development > Connect to development server. Without
   Node, an installed client can use Connect to file and pick `src/mod-manifest.json`.
4. Code and CSS changes sync on save. After any manifest change, use Reload manifest (or connect
   again): the manifest does not sync.
5. Disconnect embeds the mod in the analysis and signs it with your code-trust certificate. If
   Spotfire cannot sign, your account has no code-trust certificate on the server you are logged
   in to; ask the Spotfire administrator.

## The test harness

The harness loads `index.html` into jsdom, replaces `Spotfire` with a mock (initialize, reader,
properties, data view, rows, axes, controls, render context) and runs `main.js` in the page. Test
per mode and state:

- elements drawn (svg, paths, rows) and key text;
- marking calls for click and Ctrl+click;
- the placeholder for missing axes, the expired data view, the error path, and that
  `signalRenderComplete` is called on each;
- the theme taken from `getRenderContext().styling` (use a dark canvas in the mock);
- popout changes: three changes in a row with mock properties that refuse a stale instance.

`assets/demo-layers/test-harness.js` is a complete example for a mod with layers.

The harness evaluates `main.js` in its own scope: do not give mod functions names that shadow the
harness's own (`fs`, `path`).

`el.dispatchEvent(...)` skips hit testing, so a wrapper that swallows real pointer input passes a
jsdom test. Drive at least one suite with real input in a headless browser (Chrome DevTools
`Input.dispatchMouseEvent` for hover, drag, click and wheel) and assert that
`document.elementFromPoint` over the plot returns the interactive element.

## Delivery

- A zip of the project without `node_modules`, and a README with: Node setup (including the
  PowerShell note), `npm install` and `npm run server`, connecting in Analyst (development server
  or Connect to file), the Reload manifest rule, an axis wiring table with the exact expressions
  (including any NEST hierarchy), and the aggregation (None) of every continuous axis.
- For a published analysis, the mod comes from the library (see layers-and-scripting.md, "Mod
  origin and delivery").
- When the mod is fed by a Python data function, the data function's output types matter: see the
  `writing-spotfire-data-functions` skill.
