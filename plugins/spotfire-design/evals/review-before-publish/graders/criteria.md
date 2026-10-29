---
type: llm
weight: 1
---
Grade the assistant's review of the "Tank Inventory Review" DXP.

Pass when the review identifies, with a concrete fix for each, at least 10 of these 13 findings:

1. The KPI chart should become an HTML KPI band (caption and value per card, values from
   formatted document properties).
2. The bar chart and line chart use different markings (`Marking` and `Marking (2)`), so marking in
   one does not update the other the way users expect; the review proposes a shared marking or a
   relation and a check that every visual reacts.
3. The line chart limited by a marking with ShowEmpty is empty when nothing is marked; it should
   show all rows or a message telling the user what to mark.
4. The Filters panel should show only the columns users slice by; `Row ID`, `Latitude`,
   `Longitude` and `Sim Seed` (and helper tables) should be hidden.
5. Noise Level and Random Seed are generator settings on a working page; they belong on a Data
   Generation page placed last and labelled for advanced users (the Simulator Settings page fits).
6. The Map Color By control belongs next to the map, not in the sidebar.
7. The data function comment contains a TODO, an internal version tag and design history; all text
   and code comments must be customer-ready.
8. Auto-generated names must go: `Untitled` data function (Title Case verb + object name),
   `Page (2)`, `Marking (2)`.
9. The scratch page and the unused table `tmp_join` must be removed.
10. `LEVEL_HISTORY` must be embedded, and the DXP must not keep the local file path.
11. A cover page is missing; it must be first and its first sentence must state the business
    problem, so the planned "This Spotfire dashboard uses advanced analytics" opening must be
    rewritten.
12. The About page should become a Method page that explains the calculations in plain words
    (and a Guide or setup guide should cover the data other sites must supply, with a staging or
    mapping step for their own data).
13. Someone other than the author must open it from the library on a clean machine with HTML
    sanitation on before publishing (plus release notes and screenshots).

Also required: the findings are ordered or labelled by severity, with broken behaviour (empty
visual, split marking, linked local file) ahead of polish.

Fail when the review invents Spotfire behaviour that contradicts the points above, or recommends
publishing without the clean-machine test by someone other than the author.
