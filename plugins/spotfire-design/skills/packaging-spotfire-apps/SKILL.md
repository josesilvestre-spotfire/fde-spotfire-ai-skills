---
name: packaging-spotfire-apps
description: Packages a Spotfire analysis so that people other than its author can find, open, understand and trust it. Defines the parts of a delivered app (DXP with embedded data, cover page, working pages, Method and Guide pages, data staging for users' own data, Data Generation page, release notes, setup and data guide, screenshots, article), the page order, the content of the cover and Method pages from the App Brief and Logic Spec, and a publishing checklist covering library location and descriptions, naming, leftover pages and tables, local paths, clean-machine and Web Player tests, screenshots and the article. Use it when an analysis is about to be handed over, published to a Spotfire library or shared with another team or customer, or when someone asks what a finished Spotfire app must include.
metadata:
  maturity: Assembled from proven parts, not run as a whole
---

# Packaging Spotfire apps

You turn a working analysis into a package another team can use without its author: the right
pages in the right order, text that explains the problem and the method, data and code inside the
DXP, and a checklist that someone other than the author signs off.

Inputs: `app-brief.md` and `logic-spec.md` in `$DXP_WORKSPACE/apps/<AppSlug>/` (formats:
[references/app-brief-format.md](references/app-brief-format.md),
[references/logic-spec-format.md](references/logic-spec-format.md)), the built DXP, and the names
checked against [references/naming-standard.md](references/naming-standard.md).

## Parts of a delivered app

| Part | Content | Source |
|---|---|---|
| DXP | All pages below, data embedded, data functions and scripts inside, mods from the library or pinned | `building-spotfire-dxps` |
| Cover page | App name, the business problem, who it is for, where to start | App Brief |
| Working pages | The pages users work in, in the order they work | Design (`spotfire-app-design-rules`) |
| Method page | Each calculation behind a KPI: plain formula, inputs, units, assumptions, limits | Logic Spec |
| Guide page | Every page, table, key column with units, data function, button and requirement | The built DXP |
| Data Staging page | Load and map the user's own data; a validation readout (found, mapped, defaulted, missing) | App Brief data sources; only when users bring their own data |
| Data Generation page | Generator and calibration settings for advanced users | Only when the app generates data |
| Release notes | Version, date, Spotfire version tested, changes, scope, known issues, third-party licenses | You |
| Setup and data guide | Data model with required and optional columns, mapping, missing-data behaviour, Python packages | App Brief, Logic Spec |
| Screenshots | Every page, current build, nothing personal on screen | `testing-dxps-through-the-ui` |
| Article or overview | Business problem first, page walkthrough, data requirements, method summary, download link | You |
| Architecture diagram | Data sources, data functions, tables, pages, actions | You (Mermaid) |

Content outlines and templates for each part: [references/page-content.md](references/page-content.md).
Sanitizer-safe HTML starting points: [assets/cover-page.html](assets/cover-page.html) and
[assets/method-page.html](assets/method-page.html) (built to the sanitizer rules; **Not yet tested**
in Analyst).

## Page order

1. Cover page (always first; the page the analysis opens on).
2. Working pages, overview first, then detail, then actions.
3. Scenarios page, when the app has operator what-if scenarios.
4. Method page.
5. Guide page (a small app may merge it into the Method page).
6. Data Staging page, when users bring their own data. The cover page points to it.
7. Data Generation page, always last, when the app generates data.

Page titles follow the naming standard: Title Case, no number prefix.

## Workflow

1. **Read** the App Brief, the Logic Spec and the design decisions. Inventory the built DXP's pages,
   tables, data functions, scripts, properties, markings and mods (the
   `auditing-and-comparing-dxps` skill writes this inventory).
2. **Complete the parts.** Add what is missing from the table above. Take the cover text from the
   brief's business problem and the Method page from the Logic Spec; do not write new claims that
   the brief and the Logic Spec do not support.
3. **Set the page order** above and make the cover page the active page when you save.
4. **Run the publishing checklist** in
   [references/publishing-checklist.md](references/publishing-checklist.md). Every item ends Yes, or
   N/A with the reason written in the release notes.
5. **Write the package** next to the released DXP:
   `$DXP_WORKSPACE/apps/<AppSlug>/versions/vX.Y/package/` with `RELEASE-NOTES.md`,
   `setup-guide.md`, `screenshots/`, the article and the architecture diagram. Never change a
   released DXP in place; a fix is a new version.
6. **Hand over** for review: the reviewer opens the DXP from the library on a clean machine
   (checklist P21 to P23) and signs off.

## Rules

- **Stored data only.** The DXP opens with embedded data and no connection. A live connection, if
  the app has one, is optional, documented in the setup guide, and the app still opens without it.
- **One name everywhere:** cover page, document description, file name, library item, article.
- **The version lives in the file name and the release notes** (`Heat Exchanger Fouling Review
  1.2.dxp`), not in page titles or code comments.
- **Scope is written down.** The release notes list what this release does and what it leaves out
  (the App Brief's Out of scope).
- **Users' own data is the normal case.** When the brief says users bring their own data, ship the
  staging step and the setup guide's data model; the demo data stays as the default.
- **Someone other than the author signs off** the clean-machine test.
- **Customer-ready everything**, code comments included (the `spotfire-app-design-rules` skill,
  rule D11, has a checking script).
