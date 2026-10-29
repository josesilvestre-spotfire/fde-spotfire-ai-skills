# What the inventory reads, and from where

A DXP is a ZIP archive. `dxp_inventory.py` reads these entries:

| Entry | Content |
|---|---|
| `Metadata.xml` | document versions in the archive (Analyst 15.0 writes 15.0, 14.8 and 14.6) and the saving build |
| `AnalysisDocument.xml` | the newest copy of the analysis: one serialized object graph |
| `AnalysisMetadata.json` | description and keywords as the library shows them |
| `EmbeddedResources.xml` and `EmbeddedResources/N.emb` | named resources, among them `EmbeddedScripts.xml` (IronPython and JavaScript) and `CustomStyles.json` (the theme) |
| `DataTables/<id>` | embedded rows in Spotfire's internal format; counted, not read |
| `Mods/mod-N.asice` | embedded mods; counted |

## The object graph

`AnalysisDocument.xml` stores every object with an `Id`. A value written before is repeated as
`<ObjectRef Value="Id"/>`, and each type is declared once and referenced afterwards. The reader
indexes every object by id, follows references, and reads only the fields listed below.
Expressions are read as authored (`Expression`), not as displayed.

## Fields

| Section | Read from | Notes |
|---|---|---|
| pages | `Document.Pages.Pages.Items[]` | title, visible, filter panel visibility |
| visuals | `Page.Visuals.Items[]` and `Page.VisualPanels` | title, type id, table, marking, limit-by markings, where clause, axes (every content field of an axis type with an expression; trellis axes as `Trellis.<axis>`), layout as % of the page, sorted in reading order |
| text areas | `HtmlTextArea` | HTML (in `text_areas/`), controls (kind, view, label, property, script, data function), attached JavaScript names |
| mods | `ModVisualization` | id, name, version, axes, layers with their table, marking and axes |
| data functions | `DataManager.DataFunctions` and the definition XML each stores as a string | name, display name, engine, description, script, inputs with their binding expressions, outputs with their targets, update behaviour, trust stamp digest |
| scripts | `EmbeddedScripts.xml` | name, language, transaction, description, parameters, code, trust stamp digest |
| triggers | `ScriptManager.ScriptEventHandlers` | property and script name |
| document properties | `DataManager.PropertyRegistry.AnalysisProperties` | custom properties only (built-ins carry `IsStandard`): name, type, value, description |
| tables | `DataManager.Tables` | columns with type, kind (Source, Calculated, ...) and calculated expression; sources (file kind, data function output, caching) |
| markings and filtering | `DataManager.Markings`, `DataManager.Filterings`, `DataManager.Relations` | names, marking colors, relations |
| colors | marking colors; colors set in visuals (color rules, fixed colors), skipping Spotfire's default palettes; hex and rgb colors in text-area HTML; colors in the theme | for a palette review |

## Trust stamp digest

Each data function and script carries an approval stamp. The inventory shows the first eight
hex digits of the SHA-256 of the stamp, never the stamp itself. The digest changes when the
function is changed in Spotfire or through the Spotfire API. It does not change when a tool
rewrites the script bytes, and it did not change when a pushed function was trusted in Analyst
and saved.

## Limits

- Only the newest analysis copy is read. The older copies Spotfire keeps for older clients are
  scanned only by the hygiene check.
- Row counts of embedded tables are not readable without Spotfire.
- Cosmetic settings (fonts, label options, sort order, column widths) are not listed.
- Bookmarks are counted, not read.
