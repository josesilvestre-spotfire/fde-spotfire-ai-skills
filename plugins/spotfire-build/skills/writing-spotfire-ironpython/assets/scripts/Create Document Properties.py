# Create Document Properties
# Creates every document property the analysis uses, with its data type,
# default value and description. This list is the analysis's state contract:
# data functions, controls, labels and scripts use these exact names.
# Safe to run again: a property that already exists is left as it is.
# Run it once while you build the analysis, not from a button.
from System import Double, Int32, Int64, String
from Spotfire.Dxp.Data import (DataProperty, DataPropertyAttributes,
                               DataPropertyClass, DataType)

# name, data type, default value (exact .NET type), description
PROPERTIES = [
    ("SelectedAssetId", DataType.String, String(""),
     "Asset shown on the detail page"),
    ("TargetEfficiencyPct", DataType.Real, Double(65.0),
     "Efficiency target in percent"),
    ("MinPoints", DataType.Integer, Int32(24),
     "Minimum readings a pump needs before it is rated"),
    ("PumpsBelowTarget", DataType.LongInteger, Int64(0),
     "Pumps whose mean efficiency is below the target"),
    ("FleetEfficiencyText", DataType.String, String("-"),
     "Fleet efficiency formatted for the KPI band"),
    ("StatusMessage", DataType.String, String(""),
     "Last status line shown in the side panel"),
]

ATTRIBUTES = DataProperty.DefaultAttributes | DataPropertyAttributes.IsPropagated
registry = Document.Data.Properties
created = []
for name, data_type, default, description in PROPERTIES:
    if registry.ContainsProperty(DataPropertyClass.Document, name):
        continue
    try:
        # The description can only be given here: DataProperty.Description
        # is read-only once the property exists.
        prototype = DataProperty.CreateCustomPrototype(
            name, description, default, data_type, ATTRIBUTES)
        registry.AddProperty(DataPropertyClass.Document, prototype)
        created.append(name)
    except ValueError:
        # Another script created it in the meantime.
        pass

Document.Properties["StatusMessage"] = (
    "Created %d document properties: %s" % (len(created), ", ".join(created))
    if created else "All document properties already exist")
