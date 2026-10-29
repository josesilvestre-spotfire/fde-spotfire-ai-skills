---
title: Spotfire versions
---

# Spotfire versions

| Library release | Spotfire Analyst | Spotfire Python | Notes |
|---|---|---|---|
| `0.1.0-alpha.1` | 15.0 | 3.14 (bundled pandas 2.3.3) | Proven on one Windows 11 machine. Spotfire Server and Web Player behaviour is documented only where stated. |

Other Analyst versions are not yet tested. With an API index generated from your own install
(the generator is in `spotfire-reference` and `building-spotfire-dxps`), the builder checks every
Spotfire API member it uses before you run it, so a member your version lacks shows up before the
run. Without an index that check is skipped with a warning.
