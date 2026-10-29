# Publishing checklist

Run it before an analysis leaves its author. Every item ends **Yes**, or **N/A** with the reason
written in the release notes. Roles: the **author** builds the app, a **reviewer** who did not
build it tests it, a **publisher** stores it where users find it. One person may hold two roles,
never author and reviewer.

## Content and rights

| ID | Check | How to check | Role |
|---|---|---|---|
| P01 | No customer data, customer IP, personal data or internal-only content in data, text or code | Read every data table's source; run `check_customer_text.py` (`spotfire-app-design-rules`) with your private term list; read every text area | Author |
| P02 | The approvals your organization requires are recorded: legal or IP approval when the work came from a paid or customer engagement, name approval, publication approval | Ask the manager; record the approvals in the release notes | Author |
| P03 | Third-party code (copied snippets, mods, packages) has its license checked and listed | Release notes list each item with its license | Author |
| P04 | Every code file (data functions, IronPython scripts, text-area JavaScript, mod code) starts with your organization's copyright and license comment | Open each script and data function; search the app folder | Author |

## Pages and text

| ID | Check | How to check | Role |
|---|---|---|---|
| P05 | Cover page is first and is the active page when the DXP opens | Open the DXP | Author |
| P06 | The cover page's first sentence states the business problem from the App Brief | Compare with the brief | Reviewer |
| P07 | Method page covers every Logic Spec entry behind a KPI; Guide page covers every page, table, key column with units, data function, button and requirement | Tick each item against the Logic Spec and the inventory | Author |
| P08 | Descriptions on every table, column (with units), data function and its parameters, document property and script | Column properties, data function properties, document properties dialog | Author |
| P09 | The design rules D01 to D14 (`spotfire-app-design-rules`) are reviewed and every Blocker is fixed | The review table | Author |
| P10 | One app name everywhere: cover, document description, file name, library item, article | Compare the five | Reviewer |
| P11 | Units on every axis, header and KPI value; each category has one color on every page | Read every page | Reviewer |

## Names and leftovers

| ID | Check | How to check | Role |
|---|---|---|---|
| P12 | Names follow the naming standard (`naming-standard.md`): UPPER_SNAKE_CASE tables, Title Case columns with units, PascalCase document properties, Title Case pages, markings and filtering schemes | List the names from the inventory and compare | Author |
| P13 | No auto-generated names: no ` (2)` suffix, no `Untitled` data function, no default titles (`Page`, `Text Area`), no `Column 1` | Search the inventory | Author |
| P14 | No leftover scratch pages, unused tables, scripts, document properties, markings or embedded mods. Every table is used by a visual, a data function or a relation | Inventory against the pages and data functions | Author |
| P15 | No saved state passed off as design: markings cleared, filters reset, bookmarks intentional | Open the DXP and look | Author |

## Data and storage

| ID | Check | How to check | Role |
|---|---|---|---|
| P16 | Every table is embedded; no linked file; no connection the app needs to open | Data table properties per table; open on a machine without access to the sources | Author |
| P17 | No local path, user name or credential anywhere in the DXP | Unzip the DXP and search every entry for drive letters, `\Users\`, your user name, `password`, `token`, `apikey`. A file-based table keeps its source path even when embedded: load such tables from SBDF or replace the source | Author |
| P18 | Users can load their own data: a staging step with required and optional columns, column mapping, and a validation readout | Load a second dataset with renamed and missing columns | Author |
| P19 | Mods come from the library or are pinned; none is loaded from a development folder (that stores a local path) | Mod information in the DXP; P17 search | Author |
| P20 | Stored in the agreed library folder (for example `/<Team>/Published/<App Name>/`), with a library description that starts with the business problem, and keywords | Library browser | Publisher |

## Testing

| ID | Check | How to check | Role |
|---|---|---|---|
| P21 | Opened from the library on a clean machine, by someone other than the author, with HTML sanitation on: no errors; trust prompts reviewed and accepted by someone allowed to trust scripts | Clean machine or clean profile | Reviewer |
| P22 | Every page renders, every data function runs, every button, link and bookmark works, every marking reaches its visuals | Click through; the `testing-dxps-through-the-ui` skill records each step | Reviewer |
| P23 | Checked in Web Player on the target Spotfire version, when users will use Web Player | Open in Web Player | Reviewer |

## Documentation

| ID | Check | How to check | Role |
|---|---|---|---|
| P24 | Release notes: version, date, Spotfire version tested, changes, in and out of scope, known issues, third-party licenses, approvals | Template in `page-content.md` | Author |
| P25 | Setup and data guide: data model with required and optional columns, units and defaults, how to load and map own data, behaviour when data is missing, Python packages | Template in `page-content.md` | Author |
| P26 | Screenshots of every page from the released build, one window size, nothing personal or unrelated on screen | Window-only captures, names and paths redacted | Author |
| P27 | Article or overview: business problem first, page walkthrough with screenshots, data requirements, method summary, download link; demo video if your program publishes one | Outline in `page-content.md` | Author |
| P28 | The download page links the article, video and download and shows large screenshots | Open the page | Publisher |
