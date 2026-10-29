"""Neutral default style of the standard engine: the STYLE values dxpgen uses where spec.json says
nothing.

  palette   background #fcfcfa, tint #f2f1ec, ink #111110, ink-2 #4b4a46, ink-3 #8a8983,
            hair #e2e1db, accent #088bce, negative numbers #ba2c48
  type      Segoe UI everywhere; small axis text, 8-9 pt tables
  numbers   negatives in red text (#ba2c48), other cell text ink
Data colors and app-specific sizes (KPI tiles per row, cross-table widths) are not house values: an
app sets them in app.style. The document theme is not part of STYLE (no public API sets it); the
`styling-spotfire-dxps` skill covers themes and text-area styling.

A spec's app.style replaces these key by key (palette and formats entries are merged, each visual
kind's defaults are merged); house palette and format entries reach the builder only when
something uses them.
"""

PALETTE = {
    "bg": "#FCFCFA", "tint": "#F2F1EC", "ink": "#111110", "ink2": "#4B4A46",
    "ink3": "#8A8983", "hair": "#E2E1DB", "accent": "#088BCE", "neg": "#BA2C48",
}

FONT = "Segoe UI"
TEXT = "@ink"            # cell text that is not negative
NEGATIVE = "@neg"        # red text for values below zero

FORMATS = {
    "money": "$#,##0;-$#,##0",
    "musd": "$#,##0,,.0M;-$#,##0,,.0M",
    "kusd": "#,##0;(#,##0)",
    "kusd1": "#,##0.0;(#,##0.0)",
    "price": "$#,##0.00",
    "int": "#,##0",
    "num2": "#,##0.00;-#,##0.00",
    "pct0": "0%",
    "pct1": "0.0%",
    "multiple": "0.00x",
    "dec0": "0",
    "dec1": "0.0",
}

# Per engine kind (STYLE "visual"); "ref" = chart reference lines.
VISUAL = {
    "text": {"showTitle": False},
    "kpi": {"legend": False, "baseFont": 8, "emptyText": "-", "tile": None},
    "table": {"legend": False, "font": 8.5, "headerFont": 8.5, "headerBold": True},
    "cross": {"legend": False, "font": 8.5, "headerFont": 8.5, "headerBold": True, "totals": False,
              "negatives": True},
    "line": {"legend": True, "axisFont": 8, "axisTitleFont": 8, "legendFont": 8},
    "bar": {"legend": True, "axisFont": 8, "axisTitleFont": 8, "legendFont": 8},
    "scatter": {"legend": True, "axisFont": 8, "axisTitleFont": 8, "legendFont": 8},
    "ref": {"width": 1, "labelFont": 8},
}
