# Standard engine, feature part "properties": document
# properties (lib/20_data.py _data_add_property), created first, like
# Analyst's own dialog: CreateCustomPrototype(name, description, value,
# type, DefaultAttributes | IsPropagated [| IsListValued]). A list
# default is the typed List<T> Spotfire stores. net() converts a JSON
# value to the exact .NET type of a DataType name (also used for control
# values and script arguments).
# APP "properties": [[name, type, default, listValued, description], ...]
# (trailing listValued False and description "" are left out).
# @api DataProperty.CreateCustomPrototype(String, String, Object, DataType, DataPropertyAttributes)
# @api DataProperty.DefaultAttributes; DataPropertyAttributes.IsPropagated
# @api DataPropertyAttributes.IsListValued; DataManager.Properties
# @api DataPropertyRegistry.AddProperty(DataPropertyClass, DataProperty)
# @api DataPropertyClass.Document; DataType.DefaultValue
from System import String, Int32, Int64, Double, Single, Decimal
from System import Boolean, DateTime, TimeSpan
from System.Globalization import CultureInfo, NumberStyles
from System.Collections.Generic import List
from Spotfire.Dxp.Data import DataProperty, DataPropertyAttributes
from Spotfire.Dxp.Data import DataPropertyClass, DataType

# ------------------------------------------------- document properties
NET = {"String": String, "Integer": Int32, "LongInteger": Int64,
       "Real": Double, "SingleReal": Single, "Currency": Decimal,
       "Boolean": Boolean, "Date": DateTime, "DateTime": DateTime,
       "Time": DateTime, "TimeSpan": TimeSpan}
INV = CultureInfo.InvariantCulture


def net(type_, value):
    """JSON value -> the .NET value of a Spotfire DataType name."""
    if value is None:
        return None
    if type_ in ("Date", "DateTime", "Time"):
        return DateTime.Parse(str(value), INV)
    if type_ == "TimeSpan":
        return TimeSpan.Parse(str(value), INV)
    if type_ == "Currency":
        return Decimal.Parse(str(value), NumberStyles.Float, INV)
    if type_ == "String":
        return String(str(value))
    if type_ in ("Real", "SingleReal"):
        return NET[type_](float(value))
    return NET[type_](value)


def add_property(p):
    name, type_, default = p[0], p[1], p[2]
    listed = len(p) > 3 and p[3]
    dtype = getattr(DataType, type_)
    attrs = (DataProperty.DefaultAttributes
             | DataPropertyAttributes.IsPropagated)
    if listed:
        attrs = attrs | DataPropertyAttributes.IsListValued
        value = List[NET[type_]]()
        for item in default or []:
            value.Add(net(type_, item))
    elif default is None:
        value = dtype.DefaultValue
    else:
        value = net(type_, default)
    proto = DataProperty.CreateCustomPrototype(
        name, p[4] if len(p) > 4 else "", value, dtype, attrs)
    Document.Data.Properties.AddProperty(DataPropertyClass.Document, proto)
