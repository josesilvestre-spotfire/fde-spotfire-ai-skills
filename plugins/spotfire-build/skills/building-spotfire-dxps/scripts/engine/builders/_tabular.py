# Standard engine, shared part "_tabular": helpers of the table
# and cross-table builders (included once when an app uses either; a file
# whose name starts with "_" is a shared part, never a kind). Both
# helpers are styling, so they exist from the quick tier up.
from System import Double
from Spotfire.Dxp.Application.Visuals import CategoryKey
from Spotfire.Dxp.Application.Visuals.ConditionalColoring import (
    ConditionValue, RuleComparisonOperator)
from Spotfire.Dxp.Data import DataType

# @tier quick
# @api TablePlot.TableFontMetadata; TablePlot.TableHeaderFontMetadata
# @api CrossTablePlot.TableFontMetadata; CrossTablePlot.TableHeaderFontMetadata
# @api TablePlot.Colorings; CrossTablePlot.Colorings; ColoringCollection.AddNew
# @api ColoringCollection.AddMapping(CategoryKey, Coloring)
# @api ColoringCollection.DefaultNumericReference; Coloring.Clear
# @api Coloring.DefaultColor; Coloring.AddThresholdColorRule
# @api Coloring.SetColorOnText; ConditionValue.CreateLiteral(Object, DataType)
# @api RuleComparisonOperator.Less; CategoryKey.ctor(Object[])
# @set TablePlot.TableFontMetadata; TablePlot.TableHeaderFontMetadata
# @set CrossTablePlot.TableFontMetadata
# @set CrossTablePlot.TableHeaderFontMetadata
# @set ColoringCollection.DefaultNumericReference; Coloring.DefaultColor
# @set Coloring.SetColorOnText
# ------------------------------------------------ table, cross table
def table_fonts(content, vs):
    content.TableFontMetadata = font(opt(vs, "font"))
    content.TableHeaderFontMetadata = font(opt(vs, "headerFont"),
                                           bool(opt(vs, "headerBold")))


def negatives(content, columns):
    """Red text below zero, other values in STYLE['text']: on the given
    table columns, or on every numeric measure when columns is None."""
    colorings = content.Colorings
    c = colorings.AddNew("Negative values")
    if columns:
        for name in columns:
            colorings.AddMapping(CategoryKey(name), c)
    else:
        colorings.DefaultNumericReference = c
    c.Clear()
    c.DefaultColor = rgb(STYLE["text"])
    zero = ConditionValue.CreateLiteral(Double(0.0), DataType.Real)
    c.AddThresholdColorRule(RuleComparisonOperator.Less, zero,
                            rgb(STYLE["negative"]))
    c.SetColorOnText = True
# @end
