# Standard engine, feature part "settings": the references/spec-format.md visual
# settings escape hatch (lib/00_core.py apply_settings and
# _core_convert_for), run after the visual's builder and data links.
# Each dotted path is relative to the visual's content object (the
# LineChart, TablePlot, KpiChart, ... that Visual.As returns; IronPython
# resolves members on the runtime type): getattr walks it, the last
# part is set through setattr with the value converted to the public
# property's type - enum by member name (flags "A, B"), Color from
# '#RRGGBB' / '#AARRGGBB', Boolean, Int32, Int64, Double, Single,
# String, a public static member of a pseudo-enum class by name (else
# the value as is). One ok(...) per path, so a bad path never blocks
# the others; dxpgen checks every path against the API index first.
# APP visual "settings": {dotted path: JSON value}.
# @api Visual.As; VisualContent
import clr
from System import Boolean, Int32, Int64, Double, Single, String, Enum
from System.Drawing import Color
from System.Reflection import BindingFlags
from Spotfire.Dxp.Application.Visuals import VisualContent

# ----------------------------------------------------- settings hatch
PUBLIC = BindingFlags.Instance | BindingFlags.Public
STATIC_PUBLIC = BindingFlags.Static | BindingFlags.Public
PLAIN = ((Boolean, bool), (Int32, int), (Int64, int), (Double, float),
         (Single, float), (String, str))


def setting_value(ptype, value):
    """A JSON value -> the property's .NET type."""
    if value is None:
        return None
    if ptype.IsEnum:
        return Enum.Parse(ptype, str(value))
    if ptype == clr.GetClrType(Color):
        h = str(value).strip()
        if len(h) == 9:
            return Color.FromArgb(int(h[1:3], 16), int(h[3:5], 16),
                                  int(h[5:7], 16), int(h[7:9], 16))
        return rgb(h)
    for net_type, py in PLAIN:
        if ptype == clr.GetClrType(net_type):
            return net_type(py(value))
    if isinstance(value, str):
        member = ptype.GetProperty(value, STATIC_PUBLIC)
        if member is not None:
            return member.GetValue(None, None)
        field = ptype.GetField(value, STATIC_PUBLIC)
        if field is not None:
            return field.GetValue(None)
    return value


def set_setting(content, path, value):
    parts = path.split(".")
    target = content
    for part in parts[:-1]:
        target = getattr(target, part)
    prop = target.GetType().GetProperty(parts[-1], PUBLIC)
    if prop is None:
        raise Exception("no public property " + parts[-1] + " on "
                        + target.GetType().FullName)
    setattr(target, parts[-1], setting_value(prop.PropertyType, value))


def visual_settings(v, vs):
    content = v.As[VisualContent]()
    for path in sorted(vs["settings"]):
        ok(vs["id"] + ": setting " + path, set_setting, content, path,
           vs["settings"][path])
