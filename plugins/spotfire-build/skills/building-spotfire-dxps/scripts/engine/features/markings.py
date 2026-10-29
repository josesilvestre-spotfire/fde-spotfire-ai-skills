# Standard engine, feature part "markings": the markings
# besides the default one (lib/20_data.py _data_add_marking). The
# default marking stays core's (APP "marking", the renamed built-in).
# APP "markings": [[name, color or None], ...] (default marking not
# included). API-created markings start black, so give them a color.
# @api DataManager.Markings; DataMarkingSelectionCollection.Add(String)
# @api DataMarkingSelection.Color
# @set DataMarkingSelection.Color

# ------------------------------------------------------------ markings
def add_marking(name, color):
    m = Document.Data.Markings.Add(name)
    if color:
        m.Color = rgb(color)
